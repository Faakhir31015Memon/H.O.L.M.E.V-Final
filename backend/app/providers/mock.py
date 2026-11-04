"""Deterministic adapter used by every brain test. Nothing here talks to the network."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.providers.base import (
    AdapterHealth,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
    ModelInfo,
    StreamChunk,
    estimate_tokens,
)

CapabilitySet = {
    "chat", "reasoning", "coding", "summarization", "embedding",
    "vision", "tool_use", "long_context", "structured_output",
}


class MockAdapter:
    """Replays scripted replies so orchestrator behaviour is reproducible.

    `replies` may be a plain string, a dict (serialised to JSON), or a callable
    taking the request and returning a string. When the queue is empty the
    adapter falls back to `default_reply`.
    """

    provider = "mock"

    def __init__(
        self,
        replies: list[Any] | None = None,
        models: list[ModelInfo] | None = None,
        fail_with: str | None = None,
        default_reply: str = "mock response",
    ) -> None:
        self._replies: deque[Any] = deque(replies or [])
        self._models = models or [
            ModelInfo(provider="mock", name="mock-chat", capabilities={"chat", "reasoning", "tool_use"}),
            ModelInfo(provider="mock", name="mock-coder", capabilities={"chat", "coding", "tool_use"}),
        ]
        self.fail_with = fail_with
        self.default_reply = default_reply
        self.requests: list[GenerationRequest] = []

    def queue(self, reply: Any) -> None:
        self._replies.append(reply)

    def replace_models(self, models: list[ModelInfo]) -> None:
        """Simulate `ollama rm` / `ollama pull` changing what is on disk."""

        self._models = list(models)

    def reset(self) -> None:
        self._replies.clear()
        self.requests.clear()

    @property
    def call_count(self) -> int:
        return len(self.requests)

    async def health(self) -> AdapterHealth:
        return AdapterHealth(provider=self.provider, ok=self.fail_with is None, detail="mock")

    async def list_models(self) -> list[ModelInfo]:
        return list(self._models)

    async def capabilities(self, model: str) -> ModelCapabilities:
        for info in self._models:
            if info.name == model:
                return ModelCapabilities(
                    model=model,
                    capabilities=info.capabilities,  # type: ignore[arg-type]
                    context_window=info.context_window,
                    supports_streaming=True,
                    supports_json_mode=True,
                    is_local=True,
                )
        return ModelCapabilities(model=model, capabilities={"chat"}, is_local=True)

    def _text_for(self, req: GenerationRequest) -> str:
        reply = self._replies.popleft() if self._replies else self.default_reply
        if callable(reply):
            reply = reply(req)
        if isinstance(reply, (dict, list)):
            import json

            return json.dumps(reply)
        return str(reply)

    async def generate(self, req: GenerationRequest) -> GenerationResult:
        self.requests.append(req)
        if req.control.cancelled:
            return GenerationResult(ok=False, model=req.model, provider=self.provider, error="cancelled")
        if self.fail_with:
            return GenerationResult(ok=False, model=req.model, provider=self.provider, error=self.fail_with)
        text = self._text_for(req)
        prompt_text = (req.system or "") + " ".join(m.content for m in req.messages)
        return GenerationResult(
            ok=True,
            text=text,
            model=req.model,
            provider=self.provider,
            latency_ms=1,
            input_tokens_est=estimate_tokens(prompt_text),
            output_tokens_est=estimate_tokens(text),
        )

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamChunk]:
        result = await self.generate(req)
        if not result.ok:
            yield StreamChunk(done=True, error=result.error)
            return
        words = result.text.split(" ")
        for i, word in enumerate(words):
            if req.control.cancelled:
                yield StreamChunk(done=True, error="cancelled")
                return
            yield StreamChunk(delta=word + (" " if i < len(words) - 1 else ""))
        yield StreamChunk(done=True)


def scripted_json(payload: dict[str, Any]) -> Callable[[GenerationRequest], str]:
    """Convenience for tests: reply with a fixed JSON object."""

    import json

    return lambda _req: json.dumps(payload)
