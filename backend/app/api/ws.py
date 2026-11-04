"""WebSocket fan-out.

One subscriber on the event bus feeds every live socket, so the number of
listeners never multiplies work inside the orchestrator. A socket only sees the
session it subscribed to, and a socket that stops draining is dropped rather than
allowed to stall the bus.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config.settings import settings
from app.events.bus import SystemEvent

logger = logging.getLogger("holmev.ws")
router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    def __init__(self) -> None:
        self._sockets: dict[WebSocket, tuple[str, asyncio.Queue]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> asyncio.Queue:
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._sockets[websocket] = (session_id, queue)
        await self._send(websocket, {"type": "CONNECTED", "data": {"session_id": session_id}})
        return queue

    def disconnect(self, websocket: WebSocket) -> None:
        self._sockets.pop(websocket, None)

    def publish(self, event: SystemEvent) -> None:
        """Called from the bus; never blocks it. A slow viewer loses events, not the system."""

        for _websocket, (session_id, queue) in list(self._sockets.items()):
            if session_id and event.session_id != session_id:
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("dropping an event for a socket that stopped reading")

    async def pump(self, websocket: WebSocket) -> None:
        entry = self._sockets.get(websocket)
        if entry is None:
            return
        queue = entry[1]
        while True:
            event = await queue.get()
            await self._send(websocket, {"type": "SYSTEM_EVENT", "data": event.model_dump()})

    async def _send(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_json(message)
        except Exception as exc:  # a socket that dies mid-send is a normal event, not a crash
            logger.info("dropping a closed socket: %s", type(exc).__name__)
            self.disconnect(websocket)


ws_manager = ConnectionManager()


def _authorised(supplied: str | None) -> bool:
    if not settings.API_TOKEN:
        return True
    return bool(supplied) and hmac.compare_digest(supplied, settings.API_TOKEN)


async def bus_to_sockets(event: SystemEvent) -> None:
    """The single bridge from the event bus to every live socket."""

    ws_manager.publish(event)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str = Query(default="default_session", max_length=120),
    token: str | None = Query(default=None, max_length=200),
):
    """Live events plus a text-command channel for the desktop shell."""

    if not _authorised(token):
        await websocket.close(code=4401)
        return

    await ws_manager.connect(websocket, session_id)
    feeder = asyncio.create_task(ws_manager.pump(websocket))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await ws_manager._send(websocket, {"type": "ERROR", "data": {"detail": "send JSON"}})
                continue
            answer = await _handle(payload, session_id)
            await ws_manager._send(websocket, answer)
    except WebSocketDisconnect:
        pass
    finally:
        feeder.cancel()
        ws_manager.disconnect(websocket)


async def _handle(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    msg_type = payload.get("type")

    if msg_type == "PING":
        return {"type": "PONG", "data": {}}

    if msg_type == "CHAT":
        from app.brain.orchestrator import orchestrator

        outcome = await orchestrator.run(
            str(payload.get("text") or ""),
            session_id=str(payload.get("session_id") or session_id),
            emotion=payload.get("emotion"),
        )
        return {"type": "CHAT_REPLY", "data": outcome.as_dict()}

    if msg_type == "VOICE_INPUT":
        from app.bootstrap import ensure_monorepo_path

        ensure_monorepo_path()
        from python_services.voice.voice_manager import voice_manager

        return {"type": "VOICE_RESPONSE", "data": await voice_manager.handle_user_speech(
            str(payload.get("text") or ""), session_id=session_id
        )}

    if msg_type == "STOP":
        from app.security.stop import emergency_stop

        return {"type": "STOP_RESULT", "data": await emergency_stop.engage(reason="websocket STOP")}

    if msg_type == "GESTURE_LANDMARKS":
        from app.bootstrap import ensure_monorepo_path

        ensure_monorepo_path()
        from python_services.gesture.gesture_service import gesture_service

        return {"type": "GESTURE_RESULT", "data": gesture_service.process_camera_landmarks(payload.get("landmarks"))}

    return {"type": "ERROR", "data": {"detail": f"unknown message type '{msg_type}'"}}
