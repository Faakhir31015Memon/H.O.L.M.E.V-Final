import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Callable, Awaitable
from pydantic import BaseModel, Field

class SystemEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "system"
    session_id: str = "default_session"
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any] = Field(default_factory=dict)

class EventBus:
    def __init__(self):
        self._subscribers: List[Callable[[SystemEvent], Awaitable[None]]] = []

    def subscribe(self, callback: Callable[[SystemEvent], Awaitable[None]]):
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[SystemEvent], Awaitable[None]]):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def emit(self, event: SystemEvent):
        for sub in self._subscribers:
            try:
                await sub(event)
            except Exception:
                pass

event_bus = EventBus()
