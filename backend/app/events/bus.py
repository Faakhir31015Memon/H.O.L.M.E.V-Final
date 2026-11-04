"""Typed event bus with a bounded replay buffer.

The orchestrator narrates itself through these events, and the SSE endpoint
replays the tail of that buffer so a client that connects late - or reconnects -
sees what it missed instead of guessing from a spinner.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("holmev.events")


class EventKind:
    """Every event name the brain emits. Anything else is a bug waiting to confuse a client."""

    RUN_STARTED = "RUN_STARTED"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_FINISHED = "STAGE_FINISHED"
    UNDERSTOOD = "UNDERSTOOD"
    PLAN_READY = "PLAN_READY"
    ROUTING_DECIDED = "ROUTING_DECIDED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_DECIDED = "APPROVAL_DECIDED"
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"
    STEP_UNVERIFIED = "STEP_UNVERIFIED"
    TOOL_DELTA = "TOOL_DELTA"
    MEMORY_PROPOSED = "MEMORY_PROPOSED"
    REPLY_DELTA = "REPLY_DELTA"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_CANCELLED = "RUN_CANCELLED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    EMERGENCY_RESUME = "EMERGENCY_RESUME"
    VOICE_STATE_CHANGED = "VOICE_STATE_CHANGED"
    # Legacy names still emitted by older subsystems.
    AI_THINKING = "AI_THINKING"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"


STAGE_NAMES = (
    "CREATED",
    "UNDERSTANDING",
    "PLANNING",
    "ROUTING",
    "AWAITING_APPROVAL",
    "EXECUTING",
    "VERIFYING",
    "REPORTING",
    "COMPLETED",
)


class SystemEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "system"
    session_id: str = "default_session"
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    payload: dict[str, Any] = Field(default_factory=dict)


Subscriber = Callable[[SystemEvent], Awaitable[None]]


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._subscribers: list[Subscriber] = []
        self._history: deque[SystemEvent] = deque(maxlen=history)

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def emit(self, event: SystemEvent) -> SystemEvent:
        self._history.append(event)
        for sub in list(self._subscribers):
            try:
                await sub(event)
            except Exception as exc:
                # A UI listener must never be able to abort a run.
                logger.debug("event subscriber failed for %s: %s", event.event_type, exc)
        return event

    async def emit_kind(
        self, event_type: str, *, source: str = "orchestrator", session_id: str = "default_session",
        correlation_id: str | None = None, payload: dict[str, Any] | None = None
    ) -> SystemEvent:
        return await self.emit(
            SystemEvent(
                event_type=event_type,
                source=source,
                session_id=session_id,
                correlation_id=correlation_id or str(uuid.uuid4()),
                payload=payload or {},
            )
        )

    def recent(
        self, *, session_id: str | None = None, correlation_id: str | None = None, since: str | None = None,
        limit: int = 100
    ) -> list[SystemEvent]:
        events = list(self._history)
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        if correlation_id:
            events = [e for e in events if e.correlation_id == correlation_id]
        if since:
            ids = [event.event_id for event in events]
            events = events[ids.index(since) + 1 :] if since in ids else []
        return events[-limit:]

    def clear_history(self) -> None:
        self._history.clear()


event_bus = EventBus()
