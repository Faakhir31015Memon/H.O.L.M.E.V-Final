import sys
from pathlib import Path

# Add backend directory to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
backend_dir = root_dir / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import asyncio
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel
from app.events.bus import event_bus, SystemEvent

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

class VoiceDiagnostics(BaseModel):
    state: str
    microphone_status: str
    input_level: float
    vad_active: bool
    stt_connected: bool
    tts_playing: bool
    active_audio_sessions: int

class VoiceManager:
    def __init__(self):
        self.state: str = VoiceState.DEACTIVATED
        self.active_audio_sessions: int = 0
        self.is_listening: bool = False
        self.is_speaking: bool = False
        self.current_tts_task: Optional[asyncio.Task] = None
        self.input_level: float = 0.0
        self.vad_active: bool = False

    async def activate_continuous_voice(self):
        """Activation: 'Holmev chal kaam par lag ja' -> transitions to LISTENING loop."""
        self.state = VoiceState.ACTIVATING
        await self._broadcast_state()
        
        await asyncio.sleep(0.05)
        self.state = VoiceState.LISTENING
        self.is_listening = True
        self.active_audio_sessions = 1
        await self._broadcast_state()

    async def deactivate_continuous_voice(self):
        """Deactivation: 'Holmev so ja' -> stops sessions."""
        self.state = VoiceState.DEACTIVATING
        await self.cancel_tts()
        self.is_listening = False
        self.active_audio_sessions = 0
        self.state = VoiceState.DEACTIVATED
        await self._broadcast_state()

    async def handle_user_speech(self, text: str) -> Dict[str, Any]:
        """Processes real microphone speech input."""
        if not text:
            return {"status": "empty"}

        # Check for barge-in interruption if system is currently speaking
        if self.is_speaking:
            await self.cancel_tts()

        text_clean = text.lower().strip()

        activation_keywords = [
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
            "लग जा काम"
        ]

        deactivation_keywords = [
            "so ja",
            "sleep",
            "deactivate",
            "rest karo",
            "सो जा",
            "डीएक्टिवेट"
        ]

        if any(kw in text_clean for kw in activation_keywords):
            await self.activate_continuous_voice()
            return {
                "status": "activated",
                "state": self.state,
                "spoken": "Ji Boss, main active hoon. Kya hukum hai?",
                "spoken_response": "Ji Boss, main active hoon. Kya hukum hai?"
            }

        if any(kw in text_clean for kw in deactivation_keywords):
            await self.deactivate_continuous_voice()
            return {
                "status": "deactivated",
                "state": self.state,
                "spoken": "Alvida Boss.",
                "spoken_response": "Alvida Boss."
            }

        # If system is in DEACTIVATED state (standby mode)
        if self.state == VoiceState.DEACTIVATED:
            return {
                "status": "standby",
                "state": self.state,
                "spoken": "System Standby mein hai. Activate karne ke liye boliye: 'Holmev chal lag ja kaam par'",
                "spoken_response": "System Standby mein hai. Activate karne ke liye boliye: 'Holmev chal lag ja kaam par'"
            }

        self.state = VoiceState.THINKING
        await self._broadcast_state()

        from app.brain.brain import holmev_brain
        brain_result = await holmev_brain.process_user_request(text)

        spoken_text = brain_result.get("spoken_response", "Task execute ho gaya hai.")
        brain_result["state"] = VoiceState.LISTENING

        # Start TTS output
        await self.speak(spoken_text)

        # Automatically return to LISTENING in continuous mode
        if self.state != VoiceState.DEACTIVATED:
            self.state = VoiceState.LISTENING
            await self._broadcast_state()

        return brain_result

    async def speak(self, text: str):
        """Plays TTS audio with barge-in support."""
        self.state = VoiceState.SPEAKING
        self.is_speaking = True
        await self._broadcast_state()

        try:
            # Simulate non-blocking TTS audio playback
            for i in range(5):
                if not self.is_speaking:
                    break
                await asyncio.sleep(0.02)
        finally:
            if self.is_speaking:
                self.is_speaking = False

    async def cancel_tts(self):
        """Immediate barge-in cancellation."""
        if self.is_speaking or self.state == VoiceState.SPEAKING:
            self.is_speaking = False
            self.state = VoiceState.INTERRUPTED
            await self._broadcast_state()

    def get_diagnostics(self) -> VoiceDiagnostics:
        return VoiceDiagnostics(
            state=self.state,
            microphone_status="CONNECTED" if self.is_listening else "IDLE",
            input_level=0.42 if self.is_listening else 0.0,
            vad_active=self.is_listening,
            stt_connected=True,
            tts_playing=self.is_speaking,
            active_audio_sessions=self.active_audio_sessions
        )

    async def _broadcast_state(self):
        await event_bus.emit(SystemEvent(
            event_type="VOICE_STATE_CHANGED",
            source="voice_manager",
            payload=self.get_diagnostics().model_dump()
        ))

voice_manager = VoiceManager()
