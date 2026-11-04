"""Deterministic local inference over Ollama's HTTP API."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config.settings import settings
from app.providers.base import (
    AdapterHealth,
    GenerationRequest,
    GenerationResult,
    ModelAdapter,
    ModelCapabilities,
    ModelInfo,
    ProviderUnavailableError,
    StreamChunk,
    estimate_tokens,
)

logger = logging.getLogger("holmev.providers.ollama")

_CAPS_BY_PREFIX: dict[str, set[str]] = {
    "qwen2.5-coder": {"chat", "coding", "tool_use", "long_context"},
    "qwen2.5": {"chat", "reasoning", "tool_use"},
    "qwen": {"chat", "reasoning", "tool_use"},
    "llama3": {"chat", "reasoning", "tool_use"},
    "llama": {"chat", "reasoning"},
    "mistral": {"chat", "reasoning", "tool_use"},
    "deepseek-r": {"reasoning", "coding", "chat"},
    "nomic-embed": {"embedding"},
    "mxbai-embed": {"embedding"},
    "llava": {"chat", "vision"},
    "minicpm-v": {"chat", "vision"},
    "phi": {"chat", "reasoning"},
    "gemma": {"chat", "reasoning"},
}


def _caps_for(name: str) -> set[str]:
    lowered = name.lower()
    for prefix, caps in _CAPS_BY_PREFIX.items():
        if lowered.startswith(prefix):
            return set(caps)
    return {"chat"}


class OllamaAdapter(ModelAdapter):
    provider = "ollama"

    def __init__(self, base_url: str | None = None, default_model: str | None = None) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.default_model = default_model or settings.OLLAMA_DEFAULT_MODEL

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def health(self) -> AdapterHealth:
        start = time.perf_counter()
        try:
            async with self._client(4.0) as client:
                resp = await client.get("/api/tags")
            latency = int((time.perf_counter() - start) * 1000)
            if resp.status_code != 200:
                return AdapterHealth(
                    provider=self.provider, ok=False, base_url=self.base_url,
                    detail=f"HTTP {resp.status_code}", latency_ms=latency,
                )
            return AdapterHealth(
                provider=self.provider, ok=True, base_url=self.base_url,
                detail=f"{len(resp.json().get('models', []))} models available",
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - start) * 1000)
            return AdapterHealth(
                provider=self.provider, ok=False, base_url=self.base_url,
                detail=f"Ollama not reachable: {type(exc).__name__}. Start it with `ollama serve`.",
                latency_ms=latency,
            )

    async def list_models(self) -> list[ModelInfo]:
        async with self._client(8.0) as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        out: list[ModelInfo] = []
        for entry in payload.get("models", []):
            name = entry.get("name", "")
            size_gb = (entry.get("size") or 0) / 1e9
            out.append(
                ModelInfo(
                    provider=self.provider,
                    name=name,
                    capabilities={
                        cap for cap in _caps_for(name)
                        if cap in {
                            "chat", "reasoning", "coding", "summarization", "embedding",
                            "vision", "tool_use", "long_context", "structured_output",
                        }
                    },
                    context_window=self._context_window_for(name),
                    size_hint=f"{size_gb:.1f} GB",
                    ram_hint_gb=round(size_gb * 1.4 + 2.0, 1),
                    license=entry.get("details", {}).get("license") or "unknown",
                )
            )
        return out

    @staticmethod
    def _context_window_for(name: str) -> int:
        lowered = name.lower()
        if "128k" in lowered or "long" in lowered:
            return 128_000
        if "32k" in lowered:
            return 32_000
        if "coder" in lowered:
            return 32_000
        return 8_000

    async def capabilities(self, model: str) -> ModelCapabilities:
        caps = _caps_for(model)
        return ModelCapabilities(
            model=model,
            capabilities=caps,  # type: ignore[arg-type]
            context_window=self._context_window_for(model),
            supports_streaming=True,
            supports_json_mode="coder" in model.lower() or True,
            is_local=True,
            max_reasonable_speed_toks_s=25.0 if "3b" in model.lower() else 12.0,
        )

    def _payload(self, req: GenerationRequest, stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": req.temperature,
            "top_p": req.top_p,
            "num_predict": req.max_tokens,
        }
        if req.num_ctx:
            options["num_ctx"] = req.num_ctx
        if req.stop:
            options["stop"] = req.stop
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.extend({"role": m.role, "content": m.content} for m in req.messages)
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "options": options,
            "stream": stream,
        }
        if req.response_format == "json":
            payload["format"] = "json"
        return payload

    async def generate(self, req: GenerationRequest) -> GenerationResult:
        if req.control.cancelled:
            return GenerationResult(ok=False, model=req.model, provider=self.provider, error="cancelled")
        start = time.perf_counter()
        prompt_text = " ".join(m.content for m in req.messages) + (req.system or "")
        try:
            async with self._client(req.timeout_s) as client:
                resp = await client.post("/api/chat", json=self._payload(req, stream=False))
                if resp.status_code == 404:
                    raise ProviderUnavailableError(
                        f"Model '{req.model}' is not installed. Run: ollama pull {req.model}"
                    )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
        except ProviderUnavailableError as exc:
            return GenerationResult(
                ok=False, model=req.model, provider=self.provider,
                error=str(exc), latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except httpx.TimeoutException:
            return GenerationResult(
                ok=False, model=req.model, provider=self.provider,
                error=f"Ollama timed out after {req.timeout_s}s",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as exc:
            return GenerationResult(
                ok=False, model=req.model, provider=self.provider,
                error=f"Ollama request failed: {type(exc).__name__}: {exc}",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        text = (data.get("message") or {}).get("content", "")
        return GenerationResult(
            ok=True,
            text=text,
            model=req.model,
            provider=self.provider,
            latency_ms=int((time.perf_counter() - start) * 1000),
            input_tokens_est=estimate_tokens(prompt_text),
            output_tokens_est=estimate_tokens(text),
            raw={
                "eval_count": data.get("eval_count"),
                "eval_duration_ns": data.get("eval_duration"),
                "done_reason": data.get("done_reason"),
            },
        )

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamChunk]:
        if req.control.cancelled:
            yield StreamChunk(done=True, error="cancelled")
            return
        try:
            async with (
                self._client(req.timeout_s) as client,
                client.stream("POST", "/api/chat", json=self._payload(req, stream=True)) as resp,
            ):
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode(errors="replace")[:400]
                        yield StreamChunk(done=True, error=f"HTTP {resp.status_code}: {body}")
                        return
                    async for line in resp.aiter_lines():
                        if req.control.cancelled:
                            yield StreamChunk(done=True, error="cancelled")
                            return
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        delta = (event.get("message") or {}).get("content", "")
                        if delta:
                            yield StreamChunk(delta=delta)
                        if event.get("done"):
                            yield StreamChunk(done=True)
                            return
        except Exception as exc:
            yield StreamChunk(done=True, error=f"{type(exc).__name__}: {exc}")

        yield StreamChunk(done=True)


ollama_adapter = OllamaAdapter()
