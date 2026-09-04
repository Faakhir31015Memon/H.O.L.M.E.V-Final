from fastapi import APIRouter
from pydantic import BaseModel
from python-services.voice.voice_manager import voice_manager

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])

class SpeechInput(BaseModel):
    text: str

@router.post("/speak")
async def process_speech(payload: SpeechInput):
    result = await voice_manager.handle_user_speech(payload.text)
    return result

@router.post("/activate")
async def activate_voice():
    await voice_manager.activate_continuous_voice()
    return {"status": "activated", "diagnostics": voice_manager.get_diagnostics()}

@router.post("/deactivate")
async def deactivate_voice():
    await voice_manager.deactivate_continuous_voice()
    return {"status": "deactivated", "diagnostics": voice_manager.get_diagnostics()}

@router.get("/diagnostics")
async def get_voice_diagnostics():
    return voice_manager.get_diagnostics()
