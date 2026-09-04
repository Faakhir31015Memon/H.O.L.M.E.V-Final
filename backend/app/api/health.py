from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])

class HealthResponse(BaseModel):
    status: str
    services: dict

@router.get("/health", response_model=HealthResponse)
async def get_health():
    from python_services.voice.voice_manager import voice_manager
    from python_services.vision.vision_service import vision_service

    voice_diag = voice_manager.get_diagnostics()
    vision_diag = vision_service.capture_frame_analysis()

    return HealthResponse(
        status="healthy",
        services={
            "database": "online",
            "redis": "online",
            "ai": "online",
            "voice": "online" if voice_diag.stt_connected else "degraded",
            "vision": "online" if vision_diag.get("camera_status") == "ONLINE" else "offline",
            "desktop_agent": "online"
        }
    )

@router.get("/ready")
async def get_ready():
    return {"status": "ready"}

@router.get("/version")
async def get_version():
    return {"version": "1.0.0", "system": "H.O.L.M.E.V Personal AI OS"}
