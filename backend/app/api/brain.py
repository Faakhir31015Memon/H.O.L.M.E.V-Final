from fastapi import APIRouter
from pydantic import BaseModel
from app.brain.brain import holmev_brain

router = APIRouter(prefix="/api/v1/brain", tags=["Brain"])

class RequestInput(BaseModel):
    query: str
    session_id: str = "default_session"

@router.post("/process")
async def process_brain_request(payload: RequestInput):
    result = await holmev_brain.process_user_request(payload.query, session_id=payload.session_id)
    return result
