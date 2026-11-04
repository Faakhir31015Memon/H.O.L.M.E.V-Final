"""The Universal Intelligence Router.

Picks which model answers a request, explains why, and keeps a fallback chain so
a missing or crashed model degrades into an honest error instead of a silent lie.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from app.config.settings import settings
from app.engines.types import Complexity, PrivacyLevel, RoutingDecision
from app.providers.base import (
    ChatMessage,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
    RunControl,
)
from app.providers.registry import registry

logger = logging.getLogger("holmev.providers.router")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
LOCAL_PROVIDERS = ("ollama", "mock")


@dataclass
class RouteRequest:
    required_capabilities: set[str] = field(default_factory=set)
    complexity: Complexity = "simple"
    est_input_tokens: int = 200
    privacy_level: PrivacyLevel = "local_only"
    needs_json: bool = False
    preferred_model: str | None = None
    task_type: str = "chat"


@dataclass
class ModelRun:
    decision: RoutingDecision
    result: GenerationResult
    attempts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.result.ok


class NoModelAvailable(RuntimeError):
    """Raised when nothing on this device can serve the request."""

    def __init__(self, decision: RoutingDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class IntelligenceRouter:
    """Deterministic scoring: same inputs produce the same choice, always explainable."""

    def _candidate_pool(self, req: RouteRequest) -> list[ModelInfo]:
        pool = registry.models()
        if req.privacy_level == "local_only":
            pool = [model for model in pool if model.provider in LOCAL_PROVIDERS]
        return pool

    def _capability_fit(self, model: ModelInfo, req: RouteRequest) -> tuple[float, str]:
        if not req.required_capabilities:
            return 0.5, "no specific capability required"
        caps = set(model.capabilities)
        missing = {cap for cap in req.required_capabilities if cap not in caps}
        if not missing:
            return 1.0, "all required capabilities present"
        covered = len(req.required_capabilities) - len(missing)
        return covered / len(req.required_capabilities) * 0.5, f"missing {'/'.join(sorted(missing))}"

    @staticmethod
    def _context_fit(model: ModelInfo, req: RouteRequest) -> tuple[float, str]:
        window = model.context_window or 4096
        needed = req.est_input_tokens + 1024
        if needed <= window:
            return 1.0, f"window {window} covers {needed} tokens"
        return max(0.0, window / needed), f"window {window} short of {needed} tokens"

    @staticmethod
    def _speed_fit(model: ModelInfo) -> tuple[float, str]:
        lowered = model.name.lower()
        if model.provider == "mock":
            return 1.0, "mock adapter, instant"
        if model.provider == "ollama":
            if any(tag in lowered for tag in (":3b", ":1.5b", ":0.5b", "qwen2.5:3b")):
                return 0.9, "small local model, low latency"
            return 0.6, "larger local model, slower first token"
        return 0.8, "remote provider; latency not measurable from this device"

    @staticmethod
    def _preference_fit(model: ModelInfo, req: RouteRequest) -> tuple[float, str]:
        if req.preferred_model and model.name == req.preferred_model:
            return 1.0, "matches the model you selected"
        task_model = {
            "coding": settings.OLLAMA_CODER_MODEL,
            "research": settings.OLLAMA_REASONING_MODEL,
            "document": settings.OLLAMA_REASONING_MODEL,
        }.get(req.task_type)
        if task_model and model.name == task_model:
            return 0.9, f"recommended for {req.task_type} tasks"
        if model.name == settings.OLLAMA_CHAT_MODEL:
            return 0.7, "configured default chat model"
        if model.provider == "mock":
            return 0.2, "mock adapter is a test fixture, not a preference"
        return 0.4, "no preference signal"

    @staticmethod
    def _cost_fit(model: ModelInfo, req: RouteRequest) -> tuple[float, float]:
        """Returns (score, estimated_usd). Fill the price settings with real numbers."""

        if model.provider in LOCAL_PROVIDERS:
            return 1.0, 0.0
        cost = (
            req.est_input_tokens / 1000.0 * settings.EXTERNAL_COST_PER_1K_INPUT_USD
            + 400 / 1000.0 * settings.EXTERNAL_COST_PER_1K_OUTPUT_USD
        )
        return max(0.0, 1.0 - cost), cost

    @staticmethod
    def _privacy_fit(model: ModelInfo, req: RouteRequest) -> tuple[float, str]:
        is_local = model.provider in LOCAL_PROVIDERS
        if req.privacy_level == "local_only":
            return (1.0, "stays on this device") if is_local else (0.0, "blocked by local_only privacy rule")
        if is_local:
            return 1.0, "stays on this device"
        return 0.4, "data would leave this device"

    def score_models(self, req: RouteRequest) -> list[tuple[ModelInfo, float, dict[str, float], list[str]]]:
        scored: list[tuple[ModelInfo, float, dict[str, float], list[str]]] = []
        for model in self._candidate_pool(req):
            cap, cap_note = self._capability_fit(model, req)
            ctx, ctx_note = self._context_fit(model, req)
            speed, speed_note = self._speed_fit(model)
            pref, pref_note = self._preference_fit(model, req)
            cost, _ = self._cost_fit(model, req)
            privacy, privacy_note = self._privacy_fit(model, req)
            parts = {
                "capability": cap,
                "context": ctx,
                "speed": speed,
                "preference": pref,
                "cost": cost,
                "privacy": privacy,
            }
            total = (
                settings.W_CAPABILITY * cap
                + settings.W_CONTEXT * ctx
                + settings.W_SPEED * speed
                + settings.W_PREFERENCE * pref
                + settings.W_PRIVACY * privacy
                - settings.W_COST * (1.0 - cost)
            )
            notes = [
                f"capability {cap:.2f} - {cap_note}",
                f"context {ctx:.2f} - {ctx_note}",
                f"speed {speed:.2f} - {speed_note}",
                f"preference {pref:.2f} - {pref_note}",
                f"privacy {privacy:.2f} - {privacy_note}",
            ]
            scored.append((model, round(total, 4), parts, notes))
        scored.sort(key=lambda item: (-item[1], item[0].provider, item[0].name))
        return scored

    def route(self, req: RouteRequest) -> RoutingDecision:
        scored = self.score_models(req)
        privacy_ok = [item for item in scored if item[2]["privacy"] > 0.0]
        usable = [item for item in privacy_ok if item[2]["capability"] >= 0.5]

        if not usable:
            return RoutingDecision(
                model="",
                provider="none",
                reason=(
                    f"{self._no_model_reason(req)} Setup: "
                    f"{registry.missing_model_hint('ollama', settings.OLLAMA_CHAT_MODEL)}"
                ),
                alternatives=[model.key for model, _, _, _ in scored[:5]],
                privacy_level=req.privacy_level,
                degraded=True,
            )

        top_model, top_score, parts, notes = usable[0]
        _, cost_usd = self._cost_fit(top_model, req)
        # Weaker-but-usable models stay in the chain so a crashed specialist
        # degrades into a general answer instead of ending the run.
        chain = [
            (model.provider, model.name)
            for model, _, _, _ in privacy_ok
            if (model.provider, model.name) != (top_model.provider, top_model.name)
        ][:3]
        return RoutingDecision(
            model=top_model.name,
            provider=top_model.provider,
            reason=(
                f"{top_model.name} scored {top_score} of {len(usable)} capable model(s) - {notes[0]}; {notes[3]}. "
                f"{len(chain)} fallback(s) queued."
            ),
            scores=parts,
            alternatives=[model.key for model, _, _, _ in privacy_ok[1:6]],
            fallback_chain=chain,
            privacy_level=req.privacy_level,
            data_leaves_device=top_model.provider not in LOCAL_PROVIDERS,
            estimated_cost_usd=round(cost_usd, 6),
            degraded=top_model.provider == "mock",
        )

    @staticmethod
    def _no_model_reason(req: RouteRequest) -> str:
        needed = "/".join(sorted(req.required_capabilities)) or "chat"
        return (
            f"No model on this device can serve a '{needed}' request right now. "
            "Start Ollama (`ollama serve`) and pull a model, or add an API key and set "
            "BRAIN_ALLOW_EXTERNAL=true with PRIVACY_LEVEL=allow_external_with_consent."
        )

    async def run(
        self,
        req: RouteRequest,
        messages: list[ChatMessage],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        control: RunControl | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelRun:
        decision = self.route(req)
        if not decision.model:
            raise NoModelAvailable(decision)

        attempts: list[str] = []
        chain = [(decision.provider, decision.model), *decision.fallback_chain]
        last_result: GenerationResult | None = None

        for provider, model in chain:
            adapter = registry.adapter(provider)
            if adapter is None:
                attempts.append(f"{provider}:{model} (no adapter)")
                continue
            attempts.append(f"{provider}:{model}")
            request = GenerationRequest(
                model=model,
                messages=messages,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format="json" if req.needs_json else "text",
                timeout_s=settings.OLLAMA_TIMEOUT_S if provider == "ollama" else 60.0,
                num_ctx=settings.OLLAMA_NUM_CTX if provider == "ollama" else None,
                control=control or RunControl(),
                metadata=metadata or {},
            )
            try:
                result = await adapter.generate(request)
            except Exception as exc:
                logger.warning("model %s:%s raised %s", provider, model, exc)
                last_result = GenerationResult(ok=False, model=model, provider=provider, error=str(exc))
                continue
            if result.ok and result.text.strip():
                return ModelRun(decision=decision, result=result, attempts=attempts)
            last_result = result
            logger.warning("model %s:%s failed (%s); trying next in chain", provider, model, result.error)

        assert last_result is not None
        return ModelRun(decision=decision, result=last_result, attempts=attempts)

    async def run_json(
        self,
        req: RouteRequest,
        messages: list[ChatMessage],
        system: str | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any] | None, ModelRun | None, str | None]:
        """Ask for JSON, parse it defensively, and return (payload, run, error)."""

        json_req = replace(req, needs_json=True)
        run = await self.run(json_req, messages, system, **kwargs)
        cleaned = _JSON_FENCE.sub(r"\1", run.result.text).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, run, f"model returned non-JSON output: {exc}"
        if not isinstance(payload, dict):
            return None, run, "model returned JSON that is not an object"
        return payload, run, None


ai_router = IntelligenceRouter()
