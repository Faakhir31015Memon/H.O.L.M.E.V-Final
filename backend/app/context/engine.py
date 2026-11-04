"""Per-session working context.

The old engine was one global dict with a hardcoded `active_room`, so two
conversations in the same process overwrote each other's idea of which room was
active. State is now keyed by session and only changes when something actually
happened in that session.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import settings

DEFAULT_SESSION = "default_session"


@dataclass
class SessionContext:
    session_id: str
    active_room: str = ""
    active_device: str | None = None
    active_3d_object: str | None = None
    active_circuit_id: str | None = None
    active_user: str = "Boss"
    last_tool: str | None = None
    pending_disambiguation: dict[str, Any] | None = None
    recent_messages: list[dict[str, str]] = field(default_factory=list)

    def remember_turn(self, text: str, role: str = "user") -> None:
        content = (text or "").strip()
        if not content:
            return
        self.recent_messages.append({"role": role, "content": content[:1000]})
        limit = max(2, settings.CONVERSATION_HISTORY_TURNS * 2)
        if len(self.recent_messages) > limit:
            del self.recent_messages[: len(self.recent_messages) - limit]

    def apply_tool_effect(self, tool_name: str, params: dict[str, Any], data: dict[str, Any]) -> None:
        """Context moves forward only from things that actually ran."""

        self.last_tool = tool_name
        room = str(params.get("room") or data.get("room") or "").strip()
        if room:
            self.active_room = room
        device = str(data.get("device") or params.get("device") or "").strip()
        if device and "home.device" in tool_name:
            self.active_device = device
        if "threed" in tool_name:
            self.active_3d_object = str(params.get("object_type") or data.get("object_id") or "")[:80] or None
        if "circuit" in tool_name:
            self.active_circuit_id = str(data.get("circuit_id") or params.get("circuit_id") or "")[:80] or None

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_room": self.active_room,
            "active_device": self.active_device,
            "active_3d_object": self.active_3d_object,
            "active_circuit_id": self.active_circuit_id,
            "active_user": self.active_user,
            "last_tool": self.last_tool,
            "pending_disambiguation": self.pending_disambiguation,
            "recent_messages": self.recent_messages[-settings.CONVERSATION_HISTORY_TURNS :],
        }


class ContextStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str | None = None) -> SessionContext:
        key = session_id or DEFAULT_SESSION
        with self._lock:
            context = self._sessions.get(key)
            if context is None:
                context = SessionContext(session_id=key)
                self._sessions[key] = context
            return context

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    @property
    def session_ids(self) -> list[str]:
        return sorted(self._sessions)

    # --- compatibility with the call sites the old global engine exposed ---

    def update_context(self, message: str, role: str = "user", session_id: str | None = None) -> None:
        self.get(session_id).remember_turn(message, role)

    def get_full_context(self, session_id: str | None = None) -> dict[str, Any]:
        return self.get(session_id).snapshot()


context_store = ContextStore()

# Kept as the same import name the rest of the app already uses, but it is now a
# store of per-session contexts rather than one shared mutable dict.
context_engine = context_store
