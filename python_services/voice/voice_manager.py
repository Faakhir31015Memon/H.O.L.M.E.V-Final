"""Voice mode: the power switch in front of the same brain the UI uses.

Two kinds of thing happen here and they are deliberately kept apart.

* Turning voice mode on and off is a local, deterministic decision - it opens and
  closes the microphone, so it must never depend on a model guessing right.
* Everything the user actually asks for goes to `holmev_brain`, which is the
  orchestrator: understanding, planning, approval, execution, verification.

Speech input and output come from `speech_io`, which reports honestly when this
machine has no recogniser or no synthesiser. Nothing in here invents a level, a
latency, or a "connected" light any more.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
for candidate in (str(BACKEND_DIR), str(BACKEND_DIR.parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from pydantic import BaseModel

from app.events.bus import SystemEvent, event_bus
from python_services.voice.speech_io import recognizer, synthesizer

logger = logging.getLogger("holmev.voice")


class VoiceState:
    DEACTIVATED = "DEACTIVATED"
    IDLE = "IDLE"
    ACTIVATING = "ACTIVATING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"
    DEACTIVATING = "DEACTIVATING"


ACTIVATION_PHRASES = (
    "chal lag ja kam par",
    "chal lag ja kaam par",
    "chal kaam par lag ja",
    "kaam par lag",
    "kam par lag",
    "lag ja kam",
    "lag ja kaam",
    "kaam par lag ja",
    "holmev activate",
    "activate holmev",
    "sun holmev",
    "चल लग जा काम पर",
    "काम पर लग जा",
    "काम पर लग",
    "लग जा काम",
)

DEACTIVATION_PHRASES = (
    "so ja",
    "sleep",
    "deactivate",
    "rest karo",
    "सो जा",
    "डीएक्टिवेट",
)


class VoiceDiagnostics(BaseModel):
    state: str
    microphone_status: str
    input_level: float
    vad_active: bool
    stt_connected: bool
    tts_available: bool
    tts_backend: str | None
    capture_is_real: bool
    speech_is_real: bool
    active_audio_sessions: int
    detail: str | None = None


class VoiceManager:
    def __init__(self) -> None:
        self.state: str = VoiceState.DEACTIVATED
        self.active_audio_sessions: int = 0
        self.is_listening: bool = False
        self.is_speaking: bool = False
        self.current_tts_task: Optional[asyncio.Task] = None
        self.capture_is_real: bool = recognizer.available
        self.speech_is_real: bool = synthesizer.available

    # ------------------------------------------------------------------ mode switch

    async def activate_continuous_voice(self) -> dict[str, Any]:
        """Open the microphone. Refused, with the reason, when nothing can capture audio."""

        self.capture_is_real = recognizer.available
        self.state = VoiceState.ACTIVATING
        await self._broadcast_state()

        if not self.capture_is_real:
            self.state = VoiceState.ERROR
            self.is_listening = False
            self.active_audio_sessions = 0
            await self._broadcast_state()
            return {"activated": False, **recognizer.status()}

        self.state = VoiceState.LISTENING
        self.is_listening = True
        self.active_audio_sessions = 1
        await self._broadcast_state()
        return {"activated": True, "state": self.state}

    async def deactivate_continuous_voice(self) -> None:
        """Close the microphone and stop talking. Idempotent, because STOP must always work."""

        self.state = VoiceState.DEACTIVATING
        await self.cancel_tts()
        self.is_listening = False
        self.active_audio_sessions = 0
        self.state = VoiceState.DEACTIVATED
        await self._broadcast_state()

    # ------------------------------------------------------------------ one utterance

    async def listen_once(self, seconds: float = 5.0) -> dict[str, Any]:
        """Capture, transcribe locally, and return the words - without acting on them."""

        if self.is_speaking:
            await self.cancel_tts()
        result = await recognizer.listen_once(seconds)
        self.capture_is_real = result.available
        return result.as_dict()

    async def handle_user_speech(self, text: str, session_id: str = "default_session") -> dict[str, Any]:
        """Route one spoken sentence: mode words here, everything else to the brain."""

        if not (text or "").strip():
            return {"status": "empty"}

        if self.is_speaking:
            await self.cancel_tts()

        clean = text.lower().strip()
        if any(phrase in clean for phrase in ACTIVATION_PHRASES):
            activation = await self.activate_continuous_voice()
            spoken = (
                "Ji Boss, main active hoon. Kya hukum hai?"
                if activation.get("activated")
                else f"Main sun nahi sakta, Boss: {activation.get('reason')} Install: {activation.get('install')}"
            )
            await self.speak(spoken)
            return {
                "status": "activated" if activation.get("activated") else "not_activated",
                "state": self.state,
                "spoken_response": spoken,
                "voice_mode": activation,
            }

        if any(phrase in clean for phrase in DEACTIVATION_PHRASES):
            await self.deactivate_continuous_voice()
            return {"status": "deactivated", "state": self.state, "spoken_response": "Alvida Boss."}

        self.state = VoiceState.THINKING
        await self._broadcast_state()

        from app.brain.brain import holmev_brain

        # The brain returns an outcome the orchestrator verified, so a reply about
        # an action that failed to prove itself says so in words.
        brain_result = await holmev_brain.process_user_request(text, session_id=session_id)
        brain_result["state"] = VoiceState.LISTENING if self.is_listening else self.state
        brain_result.setdefault("spoken_response", "")

        await self.speak(brain_result["spoken_response"] or "...")

        if self.state != VoiceState.DEACTIVATED:
            self.state = VoiceState.LISTENING if self.is_listening else self.state
            await self._broadcast_state()
        return brain_result

    # ------------------------------------------------------------------ output

    async def speak(self, text: str) -> dict[str, Any]:
        self.state = VoiceState.SPEAKING
        self.is_speaking = True
        await self._broadcast_state()

        self.speech_is_real = synthesizer.available
        result = await synthesizer.speak(text)

        self.is_speaking = False
        if self.state == VoiceState.SPEAKING:
            self.state = VoiceState.LISTENING if self.is_listening else VoiceState.IDLE
        await self._broadcast_state()

        if not result.spoken:
            logger.info("nothing was spoken aloud: %s (%s)", result.detail, result.backend)
        return result.as_dict()

    async def cancel_tts(self) -> None:
        """Immediate barge-in."""

        if self.is_speaking or self.state == VoiceState.SPEAKING:
            synthesizer.cancel()
            self.is_speaking = False
            self.state = VoiceState.INTERRUPTED
            await self._broadcast_state()

    # ------------------------------------------------------------------ reporting

    def get_diagnostics(self) -> VoiceDiagnostics:
        listening = self.is_listening and recognizer.available
        return VoiceDiagnostics(
            state=self.state,
            microphone_status="OPEN" if listening else "CLOSED",
            # A level number we do not measure would be a fabricated meter, so it stays at 0.
            input_level=0.0,
            vad_active=listening,
            stt_connected=recognizer.available,
            tts_available=synthesizer.available,
            tts_backend=synthesizer.backend,
            capture_is_real=recognizer.available,
            speech_is_real=synthesizer.available,
            active_audio_sessions=self.active_audio_sessions,
            detail=None if recognizer.available else recognizer.status().get("reason"),
        )

    async def _broadcast_state(self) -> None:
        await event_bus.emit(
            SystemEvent(
                event_type="VOICE_STATE_CHANGED",
                source="voice_manager",
                payload=self.get_diagnostics().model_dump(),
            )
        )


voice_manager = VoiceManager()
