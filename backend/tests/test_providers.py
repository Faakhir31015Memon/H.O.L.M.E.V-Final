"""Tests for the model adapter layer and the intelligence router."""

from __future__ import annotations

import json

import pytest

from app.config.settings import settings
from app.engines.types import RoutingDecision
from app.providers.base import ChatMessage, ModelInfo, RunControl
from app.providers.mock import MockAdapter
from app.providers.registry import ModelRegistry
from app.providers.router import NoModelAvailable, RouteRequest, ai_router


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Every test gets its own registry so provider state never leaks between them."""

    reg = ModelRegistry()
    monkeypatch.setattr("app.providers.router.registry", reg)
    return reg


def make_models() -> list[ModelInfo]:
    return [
        ModelInfo(provider="ollama", name="qwen2.5:3b", capabilities={"chat"}, context_window=8000),
        ModelInfo(
            provider="ollama", name="qwen2.5-coder:7b",
            capabilities={"chat", "coding", "tool_use"}, context_window=32000,
        ),
        ModelInfo(
            provider="openai", name="gpt-4o-mini",
            capabilities={"chat", "reasoning", "coding", "tool_use", "structured_output"},
            context_window=128000,
        ),
    ]


@pytest.mark.asyncio
async def test_adapter_reports_the_models_it_lists(isolated_registry):
    adapter = MockAdapter(models=make_models())
    isolated_registry.register(adapter)
    await isolated_registry.refresh()
    listed = isolated_registry.models()
    assert {m.key for m in listed} == {
        "ollama:qwen2.5:3b", "ollama:qwen2.5-coder:7b", "openai:gpt-4o-mini"
    }
    assert isolated_registry.last_refresh is not None


@pytest.mark.asyncio
async def test_health_failure_drops_the_provider(isolated_registry):
    adapter = MockAdapter(models=make_models(), fail_with="Ollama not reachable")
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()
    assert isolated_registry.health()["ollama"].ok is False
    assert isolated_registry.models(["ollama"]) == []


@pytest.mark.asyncio
async def test_models_disappear_when_the_provider_dies_afterwards(isolated_registry):
    """A model cached while Ollama was up must not be routed to once it is down."""

    adapter = MockAdapter(models=make_models())
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()
    assert isolated_registry.models(["ollama"])

    adapter.fail_with = "Ollama not reachable"
    await isolated_registry.refresh()
    assert isolated_registry.models(["ollama"]) == []


@pytest.mark.asyncio
async def test_deleted_model_is_pruned_from_the_cache(isolated_registry):
    adapter = MockAdapter(models=make_models())
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    adapter.replace_models([m for m in make_models() if m.name != "qwen2.5-coder:7b"])
    await isolated_registry.refresh()

    keys = {m.key for m in isolated_registry.models()}
    assert "ollama:qwen2.5-coder:7b" not in keys
    assert "ollama:qwen2.5:3b" in keys


@pytest.mark.asyncio
async def test_local_only_privacy_excludes_external_providers(isolated_registry):
    adapter = MockAdapter(models=make_models())
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    decision = ai_router.route(RouteRequest(privacy_level="local_only", required_capabilities={"chat"}))
    assert decision.provider == "ollama"
    assert decision.data_leaves_device is False
    assert "gpt-4o-mini" not in decision.alternatives


@pytest.mark.asyncio
async def test_coding_task_prefers_the_coder_model(isolated_registry):
    adapter = MockAdapter(models=make_models())
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    decision = ai_router.route(
        RouteRequest(required_capabilities={"coding"}, task_type="coding", privacy_level="local_only")
    )
    assert decision.model == settings.OLLAMA_CODER_MODEL
    assert "scored" in decision.reason


@pytest.mark.asyncio
async def test_routing_is_deterministic(isolated_registry):
    adapter = MockAdapter(models=make_models())
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    req = RouteRequest(required_capabilities={"chat"}, task_type="chat")
    first = ai_router.route(req)
    for _ in range(25):
        assert ai_router.route(req).model == first.model


@pytest.mark.asyncio
async def test_external_is_instantly_blocked_under_local_only(isolated_registry):
    adapter = MockAdapter(models=[m for m in make_models() if m.provider == "openai"])
    adapter.provider = "openai"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    decision = ai_router.route(RouteRequest(privacy_level="local_only", required_capabilities={"chat"}))
    assert decision.model == ""
    assert decision.degraded is True


@pytest.mark.asyncio
async def test_external_only_chosen_when_permitted_and_flagged(isolated_registry):
    adapter = MockAdapter(models=[m for m in make_models() if m.provider == "openai"])
    adapter.provider = "openai"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    decision = ai_router.route(
        RouteRequest(privacy_level="allow_external_with_consent", required_capabilities={"chat"})
    )
    assert decision.provider == "openai"
    assert decision.data_leaves_device is True


@pytest.mark.asyncio
async def test_local_still_wins_when_external_is_permitted(isolated_registry):
    adapter = MockAdapter(models=make_models())
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    decision = ai_router.route(
        RouteRequest(privacy_level="allow_external_with_consent", required_capabilities={"chat"})
    )
    assert decision.provider == "ollama"
    assert decision.data_leaves_device is False


@pytest.mark.asyncio
async def test_route_without_models_raises_with_setup_hint(isolated_registry):
    with pytest.raises(NoModelAvailable) as exc_info:
        await ai_router.run(RouteRequest(required_capabilities={"chat"}), [ChatMessage(role="user", content="hi")])
    assert isinstance(exc_info.value.decision, RoutingDecision)
    assert "ollama pull" in exc_info.value.decision.reason


@pytest.mark.asyncio
async def test_fallback_chain_is_used_when_first_model_fails(isolated_registry):
    class FlakyFirst(MockAdapter):
        async def generate(self, req):
            if req.model == "qwen2.5-coder:7b":
                from app.providers.base import GenerationResult

                return GenerationResult(ok=False, model=req.model, provider=self.provider, error="crashed")
            return await super().generate(req)

    adapter = FlakyFirst(models=make_models(), replies=["recovered answer"])
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    run = await ai_router.run(
        RouteRequest(required_capabilities={"coding"}, task_type="coding"),
        [ChatMessage(role="user", content="write a sort")],
    )
    assert run.ok
    assert run.result.text == "recovered answer"
    assert "ollama:qwen2.5-coder:7b" in run.attempts[0] or "ollama:qwen2.5-coder:7b" in run.attempts
    assert run.decision.fallback_chain, "expected a queued fallback"


@pytest.mark.asyncio
async def test_run_json_parses_fenced_output(isolated_registry):
    payload = {"tool": "home.device.set_power", "arguments": {"room": "Hall"}}
    adapter = MockAdapter(models=make_models(), replies=[f"```json\n{json.dumps(payload)}\n```"])
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    parsed, run, error = await ai_router.run_json(
        RouteRequest(required_capabilities={"chat"}), [ChatMessage(role="user", content="turn off hall fan")]
    )
    assert error is None
    assert parsed == payload
    assert run is not None


@pytest.mark.asyncio
async def test_run_json_reports_bad_model_output_instead_of_guessing(isolated_registry):
    adapter = MockAdapter(models=make_models(), replies=["I cannot help with that."])
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    parsed, _run, error = await ai_router.run_json(
        RouteRequest(required_capabilities={"chat"}), [ChatMessage(role="user", content="anything")]
    )
    assert parsed is None
    assert error is not None and "non-JSON" in error


@pytest.mark.asyncio
async def test_cancellation_propagates_into_the_adapter(isolated_registry):
    adapter = MockAdapter(models=make_models(), replies=["should never be used"])
    adapter.provider = "ollama"
    isolated_registry.register(adapter)
    await isolated_registry.refresh()

    control = RunControl()
    control.cancel()
    run = await ai_router.run(
        RouteRequest(required_capabilities={"chat"}),
        [ChatMessage(role="user", content="hi")],
        control=control,
    )
    assert run.ok is False
    assert run.result.error == "cancelled"
