from fastapi import APIRouter
from pydantic import BaseModel
from app.brain.brain import holmev_brain

router = APIRouter(prefix="/api/v1/brain", tags=["Brain"])

class RequestInput(BaseModel):
    query: str
    session_id: str = "default_session"

@router.post("/process")
async def process_brain_request(payload: RequestInput):
    from python_services.voice.voice_manager import voice_manager
    result = await voice_manager.handle_user_speech(payload.query)
    return result
