"""Voice control endpoints.

Two rules hold here. Microphone capture never starts unless this endpoint is
asked for it, and nothing claims a microphone or a speaker exists - the engines
report their own availability, so a missing dependency shows up as a clear
"not installed" instead of a fake success.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.brain import require_token
from app.bootstrap import ensure_monorepo_path

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])


def _manager():
    """Import the voice manager only when a voice route is actually called.

    `python_services` lives at the monorepo root, so the path is prepared here
    rather than at module import time - otherwise loading the app would depend on
    the directory it happened to be started from.
    """

    ensure_monorepo_path()
    from python_services.voice.voice_manager import voice_manager

    return voice_manager


class SpeakInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ListenInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="Transcribed speech to hand to the brain")
    session_id: str = Field(default="default_session", max_length=120)


@router.post("/speak")
async def speak(payload: SpeakInput, _: None = Depends(require_token)) -> dict[str, Any]:
    manager = _manager()
    await manager.speak(payload.text)
    return {"spoken": payload.text, "diagnostics": manager.get_diagnostics().model_dump()}


@router.post("/interrupt")
async def interrupt(_: None = Depends(require_token)) -> dict[str, Any]:
    """Barge-in: stop talking immediately."""

    manager = _manager()
    await manager.cancel_tts()
    return {"interrupted": True, "diagnostics": manager.get_diagnostics().model_dump()}


@router.post("/listen/capture")
async def capture(
    seconds: float = Query(default=5.0, ge=0.5, le=30.0),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    """Open the microphone for a fixed window, transcribe locally, return the words.

    This is the only route that captures audio, and it stops by itself. It does
    not act on what it hears - feed the text to /listen or /chat for that.
    """

    result = await _manager().listen_once(seconds)
    if not result["available"]:
        raise HTTPException(status_code=503, detail=result["detail"])
    return result


@router.post("/listen")
async def listen(payload: ListenInput, _: None = Depends(require_token)) -> dict[str, Any]:
    """Hand already-transcribed words to the brain.

    Real capture and transcription live behind `stt_engine`, which reports
    honestly when no recogniser is installed. This endpoint exists so a client
    with its own microphone path (the desktop app) can feed the same spine.
    """

    manager = _manager()
    return await manager.handle_user_speech(payload.text, session_id=payload.session_id)


@router.post("/activate")
async def activate(_: None = Depends(require_token)) -> dict[str, Any]:
    """Start continuous listening. This opens the microphone, so it is an explicit action."""

    manager = _manager()
    await manager.activate_continuous_voice()
    return {
        "status": "activated",
        "diagnostics": manager.get_diagnostics().model_dump(),
        "capture_is_real": manager.capture_is_real,
    }


@router.post("/deactivate")
async def deactivate(_: None = Depends(require_token)) -> dict[str, Any]:
    manager = _manager()
    await manager.deactivate_continuous_voice()
    return {"status": "deactivated", "diagnostics": manager.get_diagnostics().model_dump()}


@router.get("/diagnostics")
async def diagnostics(_: None = Depends(require_token)) -> dict[str, Any]:
    try:
        manager = _manager()
    except Exception as exc:  # the module may be absent in a slim install
        raise HTTPException(status_code=503, detail=f"voice service unavailable: {exc}") from exc
    return {
        "diagnostics": manager.get_diagnostics().model_dump(),
        "capture_is_real": manager.capture_is_real,
        "speech_is_real": manager.speech_is_real,
    }
