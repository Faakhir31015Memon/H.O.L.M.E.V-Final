"""Model-agnostic adapter contract for the H.O.L.M.E.V intelligence layer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

Capability = Literal[
    "chat",
    "reasoning",
    "coding",
    "summarization",
    "embedding",
    "vision",
    "tool_use",
    "long_context",
    "structured_output",
]


class RunControl(BaseModel):
    """Cancellation + progress signal shared between orchestrator and adapters."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    cancel_event: asyncio.Event = Field(default_factory=asyncio.Event)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None


class AdapterHealth(BaseModel):
    provider: str
    ok: bool
    base_url: str | None = None
    detail: str | None = None
    latency_ms: int | None = None


class ModelCapabilities(BaseModel):
    model: str
    capabilities: set[Capability] = Field(default_factory=set)
    context_window: int = 4096
    supports_streaming: bool = True
    supports_json_mode: bool = False
    is_local: bool = True
    max_reasonable_speed_toks_s: float = 20.0


class ModelInfo(BaseModel):
    provider: str
    name: str
    capabilities: set[Capability] = Field(default_factory=set)
    context_window: int = 4096
    size_hint: str | None = None
    ram_hint_gb: float | None = None
    license: str | None = None
    enabled: bool = True
    last_seen: str | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.name}"


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    permission_level: int = 1


class GenerationRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    system: str | None = None
    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = 1024
    stop: list[str] | None = None
    response_format: Literal["text", "json"] = "text"
    tools: list[ToolSpec] | None = None
    timeout_s: float = 120.0
    num_ctx: int | None = None
    control: RunControl = Field(default_factory=RunControl)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationResult(BaseModel):
    ok: bool
    text: str = ""
    model: str
    provider: str
    error: str | None = None
    latency_ms: int = 0
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    raw: dict[str, Any] | None = None


class StreamChunk(BaseModel):
    delta: str = ""
    done: bool = False
    error: str | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    """Everything the brain can ask of a model provider."""

    provider: str

    async def health(self) -> AdapterHealth: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def capabilities(self, model: str) -> ModelCapabilities: ...

    async def generate(self, req: GenerationRequest) -> GenerationResult: ...

    def stream(self, req: GenerationRequest) -> AsyncIterator[StreamChunk]: ...


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot serve the request at all."""


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate. Never presented as an exact count."""

    if not text:
        return 0
    return max(1, int(len(text) / 4))
