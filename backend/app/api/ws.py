import json
import logging
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.events.bus import event_bus, SystemEvent

logger = logging.getLogger("holmev.ws")

router = APIRouter(tags=["WebSocket"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

ws_manager = ConnectionManager()

async def on_system_event(event: SystemEvent):
    await ws_manager.broadcast({
        "type": "SYSTEM_EVENT",
        "data": event.model_dump()
    })

event_bus.subscribe(on_system_event)

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            msg_type = payload.get("type")
            
            if msg_type == "VOICE_INPUT":
                from python-services.voice.voice_manager import voice_manager
                res = await voice_manager.handle_user_speech(payload.get("text", ""))
                await websocket.send_json({"type": "VOICE_RESPONSE", "data": res})
                
            elif msg_type == "GESTURE_LANDMARKS":
                from python-services.gesture.gesture_service import gesture_service
                res = gesture_service.process_camera_landmarks(payload.get("landmarks"))
                await websocket.send_json({"type": "GESTURE_RESULT", "data": res})

            elif msg_type == "PING":
                await websocket.send_json({"type": "PONG"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
