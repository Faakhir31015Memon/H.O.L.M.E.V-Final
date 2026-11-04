"""Live registry of adapters and the models they report.

The app never assumes a model is installed - it asks, caches, and tells the user
the exact `ollama pull` command for anything missing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from app.config.settings import settings
from app.providers.base import AdapterHealth, ModelAdapter, ModelInfo
from app.providers.mock import MockAdapter
from app.providers.ollama import OllamaAdapter
from app.providers.openai_compat import OpenAICompatibleAdapter

logger = logging.getLogger("holmev.providers.registry")


class ModelRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ModelAdapter] = {}
        self._models: dict[str, ModelInfo] = {}
        self._health: dict[str, AdapterHealth] = {}
        self._last_refresh: str | None = None

    def register(self, adapter: ModelAdapter) -> None:
        self._adapters[adapter.provider] = adapter

    def unregister(self, provider: str) -> None:
        self._adapters.pop(provider, None)
        self._models = {k: v for k, v in self._models.items() if v.provider != provider}

    @property
    def providers(self) -> list[str]:
        return sorted(self._adapters)

    def adapter(self, provider: str) -> ModelAdapter | None:
        return self._adapters.get(provider)

    def install_defaults(self) -> None:
        """Ollama always; the external adapter only when a key exists."""

        self.register(OllamaAdapter())
        if settings.OPENAI_API_KEY:
            self.register(OpenAICompatibleAdapter())
        if "mock" not in self._adapters:
            self.register(MockAdapter())

    async def refresh(self) -> dict[str, list[ModelInfo]]:
        per_provider: dict[str, list[ModelInfo]] = {}
        for provider, adapter in list(self._adapters.items()):
            try:
                health = await adapter.health()
            except Exception as exc:
                health = AdapterHealth(provider=provider, ok=False, detail=str(exc))
            self._health[provider] = health
            if not health.ok:
                per_provider[provider] = []
                continue
            try:
                models = await adapter.list_models()
            except Exception as exc:
                logger.warning("list_models failed for %s: %s", provider, exc)
                self._health[provider] = AdapterHealth(
                    provider=provider, ok=False, detail=f"model listing failed: {type(exc).__name__}"
                )
                models = []
            # A model that was deleted (`ollama rm`) must disappear from the
            # pool, otherwise the router keeps routing to a model that 404s.
            self._models = {k: v for k, v in self._models.items() if v.provider != provider}
            stamp = datetime.now(timezone.utc).isoformat()
            for model in models:
                model.last_seen = stamp
                self._models[model.key] = model
            per_provider[provider] = models
        self._last_refresh = datetime.now(timezone.utc).isoformat()
        return per_provider

    def models(self, providers: Iterable[str] | None = None) -> list[ModelInfo]:
        wanted = set(providers) if providers else None
        # Providers whose last health check failed would only produce a doomed
        # run, so their cached models are not offered. Providers we have never
        # checked are allowed through (health is refreshed at startup).
        unhealthy = {name for name, health in self._health.items() if not health.ok}
        return [
            model
            for model in self._models.values()
            if model.enabled
            and (wanted is None or model.provider in wanted)
            and model.provider not in unhealthy
        ]

    def find(self, provider: str, name: str) -> ModelInfo | None:
        return self._models.get(f"{provider}:{name}")

    def health(self) -> dict[str, AdapterHealth]:
        return dict(self._health)

    @property
    def last_refresh(self) -> str | None:
        return self._last_refresh

    def has_any_serving_model(self) -> bool:
        """True when at least one real (non-mock) provider reports a model."""

        for model in self._models.values():
            if model.provider == "mock":
                continue
            health = self._health.get(model.provider)
            if health is not None and health.ok:
                return True
        return False

    def missing_model_hint(self, provider: str, name: str) -> str:
        if provider == "ollama":
            return f"ollama pull {name}"
        return f"configure a working model for provider '{provider}'"


registry = ModelRegistry()
