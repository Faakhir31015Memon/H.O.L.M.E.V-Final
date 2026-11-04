"""Honest readiness reporting.

A health endpoint is only useful if it tells the truth, so every line here is
either a probe that really ran or an explicit "not probed". Nothing here opens a
microphone, a camera, or a network connection to a third party.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config.settings import settings
from app.database.session import session_scope
from app.providers.registry import registry as model_registry
from app.security.path_guard import workspace_root
from app.security.stop import emergency_stop
from app.tools.registry import tool_registry

router = APIRouter(tags=["Health"])


class Check(BaseModel):
    name: str
    status: str
    detail: str | None = None
    latency_ms: int | None = None


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str] = Field(default_factory=dict)
    checks: list[Check] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


async def _probe_database() -> Check:
    started = time.perf_counter()
    try:
        async with session_scope() as db:
            await db.execute(text("SELECT 1"))
        return Check(name="database", status="online", detail=settings.DATABASE_URL.split("://")[0],
                     latency_ms=int((time.perf_counter() - started) * 1000))
    except Exception as exc:  # a failed probe is reported, never raised out of /health
        return Check(name="database", status="offline", detail=f"{type(exc).__name__}: {exc}"[:200])


def _probe_models() -> Check:
    serving = [model for model in model_registry.models() if model.enabled and model.provider != "mock"]
    if not serving:
        return Check(
            name="models",
            status="offline",
            detail="no real model is serving. " + model_registry.missing_model_hint(
                "ollama", settings.OLLAMA_DEFAULT_MODEL
            ),
        )
    healthy = [name for name, health in model_registry.health().items() if health.ok]
    return Check(
        name="models",
        status="online" if healthy else "degraded",
        detail=f"{len(serving)} model(s) listed; providers answering: {healthy or 'none'}",
    )


def _probe_workspace() -> Check:
    root = workspace_root()
    if not root.exists():
        return Check(name="workspace", status="degraded", detail=f"'{root}' does not exist yet")
    return Check(name="workspace", status="online", detail=str(root))


def _probe_voice() -> Check:
    """Only reads the flags the voice manager already holds; never starts capture."""

    try:
        from python_services.voice.voice_manager import voice_manager
    except Exception as exc:
        return Check(name="voice", status="unavailable", detail=f"module not importable: {type(exc).__name__}")
    diagnostics = voice_manager.get_diagnostics()
    return Check(
        name="voice",
        status="online" if diagnostics.state != "DEACTIVATED" else "idle",
        detail=f"state={diagnostics.state}. Capture is only ever started by an explicit request.",
    )


@router.get("/health", response_model=HealthResponse)
@router.get("/api/health", response_model=HealthResponse)
@router.get("/api/v1/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    checks = [
        await _probe_database(),
        _probe_models(),
        _probe_workspace(),
        _probe_voice(),
        Check(name="tools", status="online", detail=f"{len(tool_registry.describe_all())} registered"),
        Check(
            name="stop_switch",
            status="engaged" if emergency_stop.engaged else "online",
            detail=emergency_stop.reason or "ready",
        ),
    ]
    services = {check.name: check.status for check in checks}
    reasons = [f"{check.name}: {check.detail}" for check in checks if check.status not in ("online", "idle")]

    overall = "healthy"
    if services.get("database") == "offline":
        overall = "unhealthy"
    elif reasons:
        overall = "degraded"

    return HealthResponse(status=overall, services=services, checks=checks, reasons=reasons[:8])


@router.get("/ready")
@router.get("/api/ready")
async def get_ready() -> dict[str, Any]:
    """Kubernetes-style readiness: true only when the database answers."""

    database = await _probe_database()
    if database.status != "online":
        return {"status": "not ready", "reason": database.detail}
    return {"status": "ready"}


@router.get("/version")
@router.get("/api/version")
async def get_version() -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "system": "H.O.L.M.E.V Personal AI OS",
        "environment": settings.ENVIRONMENT,
        "privacy_level": settings.PRIVACY_LEVEL,
        "external_models_allowed": settings.external_enabled,
    }
