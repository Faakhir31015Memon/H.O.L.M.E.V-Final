"""The brain's HTTP and SSE surface.

Every endpoint reads the state the orchestrator actually wrote. A client never
tells the server what it approved or what ran; it asks, and the answer comes from
the approvals, runs and audit tables on this device.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.brain.orchestrator import orchestrator
from app.config.settings import settings
from app.context.engine import context_store
from app.engines.memory import memory_engine
from app.engines.types import Complexity, PrivacyLevel
from app.events.bus import EventKind, SystemEvent, event_bus
from app.providers.base import ModelInfo
from app.providers.registry import registry as model_registry
from app.providers.router import RouteRequest, ai_router
from app.security.approvals import ApprovalNotFound, ApprovalRejected, approval_service
from app.security.audit import audit_log
from app.security.path_guard import workspace_root
from app.security.stop import emergency_stop
from app.security.undo import UndoUnavailable, undo_engine
from app.tools.registry import tool_registry

logger = logging.getLogger("holmev.api.brain")
router = APIRouter(prefix="/api/v1/brain", tags=["Brain"])

TERMINAL_EVENTS = {EventKind.RUN_COMPLETED, EventKind.RUN_FAILED, EventKind.RUN_CANCELLED}


# ------------------------------------------------------------------------ access

async def require_token(request: Request) -> None:
    """No token set means a loopback install answers freely.

    As soon as API_TOKEN is configured every mutating endpoint demands it: a
    brain that can move files and dial numbers must not be an open port.
    """

    if not settings.API_TOKEN:
        return
    header = request.headers.get("authorization", "")
    supplied = header.removeprefix("Bearer ").strip() or request.headers.get("x-holmev-token", "").strip()
    if not supplied or not hmac.compare_digest(supplied, settings.API_TOKEN):
        raise HTTPException(status_code=401, detail="This endpoint needs the API token.")


# ------------------------------------------------------------------------ inputs


class DocumentInput(BaseModel):
    name: str = Field(default="document", max_length=200)
    text: str = Field(default="", max_length=200_000)


class ChatInput(BaseModel):
    query: str = Field(default="", max_length=4000)
    session_id: str = Field(default="default_session", max_length=120)
    emotion: str | None = Field(default=None, max_length=60)
    documents: list[DocumentInput] = Field(default_factory=list, max_length=10)


class DecideInput(BaseModel):
    approved: bool
    resume: bool = Field(default=True, description="Continue the run once the decision is recorded")


class ForgetInput(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    session_id: str | None = Field(default=None, max_length=120)


class RoutePreviewInput(BaseModel):
    required_capabilities: list[str] = Field(default_factory=lambda: ["chat"], max_length=10)
    complexity: Complexity = "simple"
    est_input_tokens: int = Field(default=200, ge=0, le=10_000_000)
    needs_json: bool = False
    privacy_level: PrivacyLevel = "local_only"
    preferred_model: str | None = Field(default=None, max_length=200)
    task_type: str = Field(default="chat", max_length=60)


# ------------------------------------------------------------------------ running


@router.post("/chat")
async def chat(payload: ChatInput, _: None = Depends(require_token)) -> dict[str, Any]:
    """One request through the whole spine; returns when the run reaches a resting state."""

    outcome = await orchestrator.run(
        payload.query,
        session_id=payload.session_id,
        emotion=payload.emotion,
        documents=[document.model_dump() for document in payload.documents],
    )
    return outcome.as_dict()


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    """Continue a run that stopped for approval, using only the decisions on record."""

    try:
        outcome = await orchestrator.resume(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return outcome.as_dict()


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    cancelled = await orchestrator.cancel(run_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' is not live on this device.")
    return {"run_id": run_id, "cancelled": True}


@router.get("/runs")
async def recent_runs(
    session_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    return {"runs": await orchestrator.recent_runs(session_id=session_id, limit=limit)}


@router.get("/runs/{run_id}")
async def run_detail(run_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    trace = await orchestrator.run_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No run with id '{run_id}'.")
    return trace


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    since: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=400),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    """The recorded transitions for one run, inside the in-memory replay window."""

    events = event_bus.recent(correlation_id=run_id, since=since, limit=limit)
    return {
        "run_id": run_id,
        "replay_window_is_memory_only": True,
        "events": [event.model_dump() for event in events],
    }


# ------------------------------------------------------------------------ streaming


@router.get("/stream")
async def stream(
    request: Request,
    session_id: str | None = Query(default=None, max_length=120),
    run_id: str | None = Query(default=None, max_length=120),
    since: str | None = Query(default=None, max_length=80),
    replay: bool = Query(default=True),
    _: None = Depends(require_token),
) -> StreamingResponse:
    """Server-sent events: replay the tail of the log, then follow it live.

    Replaying first is what makes a refresh honest - the UI sees the stage
    transitions it missed instead of starting blank and guessing.
    """

    queue: asyncio.Queue[SystemEvent] = asyncio.Queue(maxsize=500)

    async def subscriber(event: SystemEvent) -> None:
        if session_id and event.session_id != session_id:
            return
        if run_id and event.correlation_id != run_id:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("dropping event %s: this viewer fell behind", event.event_type)

    async def pulses() -> AsyncIterator[str]:
        event_bus.subscribe(subscriber)
        try:
            if replay:
                for event in event_bus.recent(session_id=session_id, correlation_id=run_id, since=since, limit=200):
                    yield _frame(event)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _frame(event)
                if run_id and event.event_type in TERMINAL_EVENTS:
                    break
        finally:
            event_bus.unsubscribe(subscriber)

    return StreamingResponse(
        pulses(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _frame(event: SystemEvent) -> str:
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {_dumps(event)}\n\n"


def _dumps(event: SystemEvent) -> str:
    # A payload that will not serialise must not take the stream down with it.
    try:
        return json.dumps(event.model_dump(), default=str)
    except (TypeError, ValueError):
        return json.dumps({"event_id": event.event_id, "event_type": event.event_type, "payload": {}})


# ------------------------------------------------------------------------ approvals


@router.get("/approvals")
async def list_approvals(_: None = Depends(require_token)) -> dict[str, Any]:
    expired = await approval_service.expire_stale()
    pending = [approval_service.describe(record) for record in await approval_service.list_pending()]
    return {"pending": pending, "expired_just_now": expired}


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str, payload: DecideInput, _: None = Depends(require_token)
) -> dict[str, Any]:
    """Record the user's answer for one exact action, then optionally continue the run.

    The decision binds to the parameter hash the user was shown; resuming re-reads
    the plan stored server-side, so edited parameters cannot ride along on an old yes.
    """

    try:
        record = await approval_service.decide(approval_id, approved=payload.approved)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    result: dict[str, Any] = {"approval": approval_service.describe(record)}
    if payload.resume and record.run_id:
        try:
            result["run"] = (await orchestrator.resume(record.run_id)).as_dict()
        except (KeyError, ValueError) as exc:
            # The decision is already committed; say so instead of pretending it was lost.
            result["resume_error"] = str(exc)
    return result


# ------------------------------------------------------------------------ stop switch


@router.get("/stop")
async def stop_status(_: None = Depends(require_token)) -> dict[str, Any]:
    return emergency_stop.status()


@router.post("/stop")
async def engage_stop(reason: str = Query(default="user pressed STOP", max_length=200)) -> dict[str, Any]:
    """Cancel live runs and void every pending approval. Deliberately allowed without a token."""

    return await emergency_stop.engage(reason=reason)


@router.post("/stop/resume")
async def release_stop(_: None = Depends(require_token)) -> dict[str, Any]:
    return await emergency_stop.resume()


# ------------------------------------------------------------------------ undo


@router.get("/undo")
async def list_undo_records(
    run_id: str | None = Query(default=None, max_length=36),
    status: str | None = Query(default="available", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    records = await undo_engine.list_records(run_id=run_id, status=status, limit=limit)
    return {"records": [_describe_undo(record) for record in records], "count": len(records)}


@router.post("/undo/{record_id}")
async def perform_undo(record_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    """Reverse one recorded action, or say exactly why that record cannot be reversed."""

    try:
        return await undo_engine.undo(record_id)
    except UndoUnavailable as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc


def _describe_undo(record: Any) -> dict[str, Any]:
    detail = dict(record.detail or {})
    return {
        "undo_id": record.id,
        "run_id": record.run_id,
        "tool": record.tool,
        "target": record.target,
        "kind": detail.get("kind", "none"),
        "status": record.status,
        "reversible": detail.get("kind", "none") != "none",
        "reason": detail.get("reason"),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "undone_at": record.undone_at.isoformat() if record.undone_at else None,
    }


# ------------------------------------------------------------------------ home & scene


@router.get("/cameras")
async def list_cameras(_: None = Depends(require_token)) -> dict[str, Any]:
    """Declared cameras and whether each one has a URL - without touching the network."""

    from app.home.cctv_manager import cctv_manager

    cctv_manager.refresh()
    return {
        "cameras": list(cctv_manager.cameras.values()),
        "feeds_verified": False,
        "note": "nothing was probed; POST /api/v1/brain/cameras/probe asks each HTTP feed directly",
    }


@router.post("/cameras/probe")
async def probe_cameras(
    rooms: str | None = Query(default=None, max_length=200), _: None = Depends(require_token)
) -> dict[str, Any]:
    """Reach out to the configured camera URLs and report what actually answers."""

    from app.home.cctv_manager import cctv_manager

    targets = [part.strip() for part in (rooms or "").split(",") if part.strip()] or None
    return await cctv_manager.probe(targets)


@router.get("/scene")
async def read_scene(_: None = Depends(require_token)) -> dict[str, Any]:
    from app.projects.threed_manager import threed_manager

    return {
        "objects": threed_manager.get_scene(),
        "scene": threed_manager.scene_summary(),
        "bounding_box": threed_manager.bounding_box(),
    }


# ------------------------------------------------------------------------ memory


@router.get("/memories")
async def list_memories(
    state: str | None = Query(default="pending", max_length=20),
    layer: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=200, ge=1, le=1000),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    records = await memory_engine.list_memories(state=state, layer=layer, limit=limit)
    return {"memories": [record.as_dict() for record in records], "count": len(records)}


@router.post("/memories/{memory_id}/confirm")
async def confirm_memory(memory_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    record = await memory_engine.confirm(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No memory with id '{memory_id}'.")
    return {"memory": record.as_dict()}


@router.post("/memories/{memory_id}/reject")
async def reject_memory(memory_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    record = await memory_engine.reject(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No memory with id '{memory_id}'.")
    return {"memory": record.as_dict()}


@router.delete("/memories/{memory_id}")
async def forget_memory(memory_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
    if not await memory_engine.forget(memory_id):
        raise HTTPException(status_code=404, detail=f"No memory with id '{memory_id}'.")
    return {"forgotten": memory_id}


@router.post("/memories/forget")
async def forget_matching(payload: ForgetInput, _: None = Depends(require_token)) -> dict[str, Any]:
    removed = await memory_engine.forget_matching(payload.query, session=payload.session_id)
    return {"forgotten": removed, "count": len(removed)}


@router.get("/memories/export")
async def export_memories(fmt: str = Query(default="json", pattern="^(json|csv)$")) -> dict[str, str]:
    return {"format": fmt, "content": await memory_engine.export(fmt)}


# ------------------------------------------------------------------------ models + routing


@router.get("/models")
async def models(_: None = Depends(require_token)) -> dict[str, Any]:
    serving: list[ModelInfo] = [model for model in model_registry.models() if model.enabled]
    return {
        "serving": [model.model_dump() for model in serving],
        "providers": model_registry.providers,
        "adapter_health": {name: health.model_dump() for name, health in model_registry.health().items()},
        "has_real_model": model_registry.has_any_serving_model(),
        "last_refresh": model_registry.last_refresh,
        "privacy_level": settings.PRIVACY_LEVEL,
        "external_allowed": settings.external_enabled,
    }


@router.post("/models/refresh")
async def refresh_models(_: None = Depends(require_token)) -> dict[str, Any]:
    return {"models": await model_registry.refresh(), "health": _health_dump()}


def _health_dump() -> dict[str, Any]:
    return {name: health.model_dump() for name, health in model_registry.health().items()}


@router.post("/route/preview")
async def route_preview(payload: RoutePreviewInput, _: None = Depends(require_token)) -> dict[str, Any]:
    """Show the ranking for a request without running it - the router is explainable."""

    request = RouteRequest(
        required_capabilities=set(payload.required_capabilities),
        complexity=payload.complexity,
        est_input_tokens=payload.est_input_tokens,
        privacy_level=payload.privacy_level,
        needs_json=payload.needs_json,
        preferred_model=payload.preferred_model,
        task_type=payload.task_type,
    )
    return {
        "decision": ai_router.route(request).as_dict(),
        "ranking": [
            {
                "model": f"{model.provider}:{model.name}",
                "score": round(score, 3),
                "breakdown": {key: round(value, 3) for key, value in parts.items()},
                "notes": notes,
            }
            for model, score, parts, notes in ai_router.score_models(request)
        ],
    }


@router.get("/tools")
async def tools(_: None = Depends(require_token)) -> dict[str, Any]:
    """The registered catalog, with the permission level that decides approval gating."""

    catalog = tool_registry.describe_all()
    return {
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "permission_level": spec.permission_level,
                "needs_approval": spec.permission_level >= settings.APPROVAL_MIN_LEVEL,
                "parameters": spec.parameters,
            }
            for spec in catalog.values()
        ],
        "approval_min_level": settings.APPROVAL_MIN_LEVEL,
    }


# ------------------------------------------------------------------------ context + audit


@router.get("/context")
async def read_context(
    session_id: str = Query(default="default_session", max_length=120),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    return context_store.get(session_id).snapshot()


@router.get("/audit")
async def read_audit(
    run_id: str | None = Query(default=None, max_length=120),
    tool: str | None = Query(default=None, max_length=120),
    outcome: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=1000),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    entries = await audit_log.query(run_id=run_id, tool=tool, outcome=outcome, limit=limit)
    return {
        "entries": [
            {
                "id": entry.id,
                "ts": entry.ts.isoformat() if entry.ts else None,
                "actor": entry.actor,
                "action": entry.action,
                "outcome": entry.outcome,
                "run_id": entry.run_id,
                "tool": entry.tool,
                "params": entry.params,
                "permission_level": entry.permission_level,
                "error": entry.error,
            }
            for entry in entries
        ],
        "redacted": True,
    }


@router.get("/status")
async def brain_status(_: None = Depends(require_token)) -> dict[str, Any]:
    """What this device can actually do right now, in one round trip."""

    from app.communication.mobile_bridge import mobile_bridge_service

    capabilities = {
        "home_appliance_control": _home_is_real(),
        "ir_emitter": _ir_is_real(),
        "camera_feeds": _cameras_with_urls(),
        "phone_bridge": bool(mobile_bridge_service.device_connected),
        "email": mobile_bridge_service.email_is_real,
        "keyboard_automation": _pyautogui_is_available(),
        "power_actions": settings.ALLOW_SYSTEM_POWER_ACTIONS,
        "routing_server": bool(_routing_server()),
        "external_model": settings.external_enabled,
    }

    return {
        "stop": emergency_stop.status(),
        "active_runs": orchestrator.active_runs(),
        "pending_approvals": len(await approval_service.list_pending()),
        "pending_memories": await memory_engine.pending_count(),
        "reversible_actions": len(await undo_engine.list_records(status="available", limit=200)),
        "has_real_model": model_registry.has_any_serving_model(),
        "hint": (
            None
            if model_registry.has_any_serving_model()
            else model_registry.missing_model_hint("ollama", settings.OLLAMA_DEFAULT_MODEL)
        ),
        "capabilities": capabilities,
        "capabilities_note": (
            "true means the wiring exists here; false means the brain will refuse that action "
            "instead of reporting one it did not perform"
        ),
        "workspace_root": str(workspace_root()),
    }


def _home_is_real() -> bool:
    from app.devices.registry import hardware_is_real

    return hardware_is_real()


def _ir_is_real() -> bool:
    from app.home.ir_remote import ir_remote_engine

    return ir_remote_engine.hardware_connected


def _cameras_with_urls() -> int:
    from app.home.cctv_manager import cctv_manager

    return sum(1 for camera in cctv_manager.cameras.values() if camera.get("has_feed"))


def _pyautogui_is_available() -> bool:
    from app.tools import desktop_tools

    return desktop_tools.pyautogui is not None


def _routing_server() -> str:
    from app.navigation.route_engine import routing_server

    return routing_server()
