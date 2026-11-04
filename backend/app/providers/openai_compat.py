"""OpenAI-compatible adapter (OpenAI, Groq, Together, local vLLM, OpenRouter).

Credentials travel only in the Authorization header and are never logged.
Disabled entirely when no key is configured.
"""

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
    ModelCapabilities,
    ModelInfo,
    StreamChunk,
    estimate_tokens,
)

logger = logging.getLogger("holmev.providers.openai_compat")

_SENSITIVE_PATTERNS = ("api_key", "token", "secret", "authorization")


class OpenAICompatibleAdapter:
    provider = "openai_compat"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        provider_label: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.OPENAI_API_KEY
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.provider = provider_label or settings.OPENAI_PROVIDER_LABEL
        self.default_model = settings.OPENAI_DEFAULT_MODEL

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, req: GenerationRequest, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.extend({"role": m.role, "content": m.content} for m in req.messages)
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "max_tokens": req.max_tokens,
            "stream": stream,
        }
        if req.stop:
            payload["stop"] = req.stop
        if req.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if req.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in req.tools
            ]
        return payload

    async def health(self) -> AdapterHealth:
        if not self.enabled:
            return AdapterHealth(
                provider=self.provider, ok=False, base_url=self.base_url,
                detail="No API key configured - external provider disabled.",
            )
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            latency = int((time.perf_counter() - start) * 1000)
            ok = resp.status_code == 200
            return AdapterHealth(
                provider=self.provider, ok=ok, base_url=self.base_url,
                detail="reachable" if ok else f"HTTP {resp.status_code}", latency_ms=latency,
            )
        except Exception as exc:
            return AdapterHealth(
                provider=self.provider, ok=False, base_url=self.base_url,
                detail=f"{type(exc).__name__}", latency_ms=int((time.perf_counter() - start) * 1000),
            )

    async def list_models(self) -> list[ModelInfo]:
        if not self.enabled:
            return []
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        return [
            ModelInfo(
                provider=self.provider,
                name=name,
                capabilities={"chat", "reasoning", "tool_use", "structured_output"},
                context_window=128_000,
            )
            for name in sorted(ids)
        ]

    async def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            model=model,
            capabilities={"chat", "reasoning", "coding", "tool_use", "structured_output", "long_context"},
            context_window=128_000,
            supports_streaming=True,
            supports_json_mode=True,
            is_local=False,
        )

    async def generate(self, req: GenerationRequest) -> GenerationResult:
        if not self.enabled:
            return GenerationResult(
                ok=False, model=req.model, provider=self.provider,
                error="External provider disabled: no API key set.",
            )
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=req.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", headers=self._headers(), json=self._payload(req, False)
                )
                if resp.status_code == 401:
                    raise RuntimeError("Authentication rejected - check the API key.")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return GenerationResult(
                ok=False, model=req.model, provider=self.provider,
                error=f"{self.provider} request failed: {_redact(str(exc))}",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        choices = data.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
        tool_calls = (choices[0].get("message") or {}).get("tool_calls") if choices else None
        prompt_text = (req.system or "") + " ".join(m.content for m in req.messages)
        return GenerationResult(
            ok=True,
            text=text,
            model=req.model,
            provider=self.provider,
            latency_ms=int((time.perf_counter() - start) * 1000),
            input_tokens_est=estimate_tokens(prompt_text),
            output_tokens_est=estimate_tokens(text),
            raw={"tool_calls": tool_calls, "usage": data.get("usage")},
        )

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamChunk]:
        if not self.enabled:
            yield StreamChunk(done=True, error="External provider disabled: no API key set.")
            return
        try:
            async with (
                httpx.AsyncClient(timeout=req.timeout_s) as client,
                client.stream(
                    "POST", f"{self.base_url}/chat/completions", headers=self._headers(), json=self._payload(req, True)
                ) as resp,
            ):
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode(errors="replace")[:400]
                        yield StreamChunk(done=True, error=f"HTTP {resp.status_code}: {_redact(body)}")
                        return
                    async for line in resp.aiter_lines():
                        if req.control.cancelled:
                            yield StreamChunk(done=True, error="cancelled")
                            return
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            yield StreamChunk(done=True)
                            return
                        try:
                            event = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        delta = ((event.get("choices") or [{}])[0].get("delta") or {}).get("content")
                        if delta:
                            yield StreamChunk(delta=delta)
        except Exception as exc:
            yield StreamChunk(done=True, error=f"{type(exc).__name__}: {_redact(str(exc))}")
        yield StreamChunk(done=True)


def _redact(text: str) -> str:
    """Never let a credential escape into an error message or log line."""

    lowered = text.lower()
    for needle in _SENSITIVE_PATTERNS:
        if needle in lowered:
            return text[:80] + " ...[redacted]"
    return text[:300]


openai_compat_adapter = OpenAICompatibleAdapter()
