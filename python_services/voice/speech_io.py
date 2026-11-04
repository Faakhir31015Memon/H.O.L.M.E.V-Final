"""Real speech input and output, with no paid dependency and no pretending.

Two paths are wired here because both exist on an ordinary PC for free:

* **Talking** - Windows has SAPI built in, so `System.Speech` speaks through
  PowerShell with nothing installed. macOS has `say`, Linux usually `espeak-ng`.
  `pyttsx3` is preferred when the user has it.
* **Listening** - `faster-whisper` runs a local Whisper model and `sounddevice`
  reads the microphone. Both are free; neither is assumed.

Anything missing reports itself as missing, with the command that would install
it. The old version of this module returned `stt_connected=True` and a constant
input level, which meant the UI was showing a green light for hardware the code
never touched.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import shutil
import subprocess
import sys
from typing import Any

logger = logging.getLogger("holmev.voice.speech_io")

SPEAK_TIMEOUT_S = 60.0


class SynthesisResult:
    def __init__(self, spoken: bool, backend: str, detail: str) -> None:
        self.spoken = spoken
        self.backend = backend
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"spoken": self.spoken, "backend": self.backend, "detail": self.detail}


class SpeechSynthesizer:
    """Says a sentence out loud through whatever this machine really has."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self.backend: str | None = self._pick_backend()

    def _pick_backend(self) -> str | None:
        try:
            import pyttsx3  # noqa: F401  (presence is the whole test)

            return "pyttsx3"
        except Exception:
            pass
        if sys.platform == "win32" and shutil.which("powershell"):
            return "windows-sapi"
        if sys.platform == "darwin" and shutil.which("say"):
            return "mac-say"
        if shutil.which("espeak-ng"):
            return "espeak-ng"
        return None

    @property
    def available(self) -> bool:
        return self.backend is not None

    def status(self) -> dict[str, Any]:
        if self.available:
            return {"available": True, "backend": self.backend}
        return {
            "available": False,
            "backend": None,
            "reason": "no text-to-speech backend on this machine",
            "install": "pip install pyttsx3   (Windows also needs nothing: enable PowerShell)",
        }

    def _command(self, text: str) -> list[str] | None:
        if self.backend == "pyttsx3":
            return None
        if self.backend == "windows-sapi":
            # The sentence arrives as base64 in argv and is decoded inside the
            # script, so no quoting or escaping rule here can be talked into
            # running something else: the shell never sees the text as code.
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            script = (
                "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[0]));"
                "Add-Type -AssemblyName System.Speech;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.Rate=0;$s.Volume=100;$s.Speak($t)"
            )
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, encoded]
        if self.backend == "mac-say":
            return ["say", text]
        if self.backend == "espeak-ng":
            return ["espeak-ng", text]
        return None

    async def speak(self, text: str, *, rate: int = 0) -> SynthesisResult:
        clean = (text or "").strip()
        if not clean:
            return SynthesisResult(False, self.backend or "none", "nothing to say")
        if not self.available:
            return SynthesisResult(False, "none", self.status()["reason"])

        try:
            if self.backend == "pyttsx3":
                await asyncio.to_thread(self._speak_pyttsx3, clean, rate)
                return SynthesisResult(True, "pyttsx3", "handed to pyttsx3")

            command = self._command(clean)
            if command is None:
                return SynthesisResult(False, self.backend, "no command for this backend")
            self._process = await asyncio.to_thread(
                subprocess.Popen, command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._process.wait), timeout=SPEAK_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                self.cancel()
                return SynthesisResult(False, self.backend, "speech timed out and was cancelled")
            code = self._process.returncode
            self._process = None
            if code == 0:
                return SynthesisResult(True, self.backend, "spoken aloud")
            return SynthesisResult(False, self.backend, f"backend exited with code {code}")
        except FileNotFoundError as exc:
            self.backend = None
            return SynthesisResult(False, "none", f"backend binary vanished: {exc}")
        except Exception as exc:  # a broken audio device must not break the run
            logger.warning("speech synthesis failed: %s", exc)
            return SynthesisResult(False, self.backend or "none", f"{type(exc).__name__}: {exc}"[:200])

    @staticmethod
    def _speak_pyttsx3(text: str, rate: int) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        try:
            engine.setProperty("rate", max(80, min(300, 180 + rate * 20)))
            engine.say(text)
            engine.runAndWait()
        finally:
            engine.stop()

    def cancel(self) -> int | None:
        """Barge-in. Returns the number of in-flight utterances actually stopped."""

        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return 0
        process.terminate()
        return 1


class RecognitionResult:
    def __init__(self, text: str, available: bool, detail: str, duration_s: float = 0.0) -> None:
        self.text = text
        self.available = available
        self.detail = detail
        self.duration_s = duration_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "available": self.available,
            "detail": self.detail,
            "duration_s": round(self.duration_s, 2),
        }


class SpeechRecognizer:
    """Turns microphone audio into text with a local Whisper model, or says why it cannot."""

    def __init__(self, model_size: str = "base") -> None:
        self.model_size = model_size
        self._model = None
        self.sample_rate = 16000

    @property
    def available(self) -> bool:
        return self._dependency_error() is None

    def _dependency_error(self) -> str | None:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return "faster-whisper is not installed"
        try:
            import sounddevice  # noqa: F401
        except Exception:
            return "sounddevice is not installed (it needs the PortAudio runtime)"
        return None

    def status(self) -> dict[str, Any]:
        error = self._dependency_error()
        if error:
            return {
                "available": False,
                "reason": error,
                "install": "pip install faster-whisper sounddevice numpy",
                "model": self.model_size,
            }
        return {
            "available": True,
            "reason": None,
            "model": self.model_size,
            "model_loaded": self._model is not None,
        }

    def _load_model(self):
        from faster_whisper import WhisperModel

        if self._model is None:
            # compute_type="int8" keeps a base model runnable on a laptop CPU with
            # no GPU, which is the whole point of a local-first assistant.
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def _record(self, seconds: float) -> Any:
        import numpy as np
        import sounddevice as sd

        frames = sd.rec(int(seconds * self.sample_rate), samplerate=self.sample_rate, channels=1, dtype="int16")
        sd.wait()
        return frames[:, 0].astype("float32") / 32768.0

    async def listen_once(self, seconds: float = 5.0, *, language: str | None = None) -> RecognitionResult:
        error = self._dependency_error()
        if error:
            return RecognitionResult("", False, f"{error}. Install it, then try again.")

        import time

        started = time.perf_counter()
        try:
            audio = await asyncio.to_thread(self._record, min(max(seconds, 0.5), 60.0))
            model = await asyncio.to_thread(self._load_model)
            segments, _info = await asyncio.to_thread(model.transcribe, audio, language=language)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:  # a dead mic is a reportable state, not a crash
            logger.warning("recognition failed: %s", exc)
            return RecognitionResult("", True, f"{type(exc).__name__}: {exc}"[:200], time.perf_counter() - started)

        return RecognitionResult(
            text, True, "transcribed locally" if text else "captured audio but heard no words",
            time.perf_counter() - started,
        )


synthesizer = SpeechSynthesizer()
recognizer = SpeechRecognizer()
