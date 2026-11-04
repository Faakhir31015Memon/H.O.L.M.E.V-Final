"""Heuristic face/mood detection from a camera frame.

These labels are threshold heuristics over pixel statistics, NOT model outputs.
`confidence` is a fixed constant per branch and must always be presented as an
estimate; nothing downstream may claim it can see unless a camera frame was
actually supplied through a granted permission.
"""

from __future__ import annotations

from typing import Any

import numpy as np

HEURISTIC_VERSION = "haar-threshold-1"


class EmotionService:
    def __init__(self) -> None:
        # Cascades are loaded on first use so an unsupported/absent OpenCV build
        # can never take down application startup or the health endpoint.
        self._cascades: dict[str, Any] | None = None
        self._unavailable_reason: str | None = None

    def _load(self) -> dict[str, Any] | None:
        if self._cascades is not None or self._unavailable_reason is not None:
            return self._cascades
        try:
            import cv2

            get_cascade = getattr(cv2, "CascadeClassifier", None)
            if get_cascade is None or not hasattr(cv2, "data"):
                raise AttributeError(
                    "this OpenCV build has no Haar cascade support (cv2.CascadeClassifier was removed in OpenCV 5)"
                )
            self._cascades = {
                "face": get_cascade(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"),
                "eye": get_cascade(cv2.data.haarcascades + "haarcascade_eye.xml"),
                "smile": get_cascade(cv2.data.haarcascades + "haarcascade_smile.xml"),
            }
        except Exception as exc:
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
            self._cascades = None
        return self._cascades

    @property
    def available(self) -> bool:
        return self._load() is not None

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "engine": HEURISTIC_VERSION,
            "detail": self._unavailable_reason or "haar cascades loaded",
            "note": "heuristic pixel thresholds, not a trained emotion model",
        }

    def analyze_face_emotion(self, frame: np.ndarray | None) -> dict[str, Any]:
        """Return an estimated mood label for a camera frame, or an honest failure."""

        base = {
            "engine": HEURISTIC_VERSION,
            "confidence_basis": "heuristic_constant",
            "face_detected": False,
        }

        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return {**base, "status": "NO_FRAME", "emotion": "UNKNOWN", "confidence": None}

        cascades = self._load()
        if cascades is None:
            return {
                **base,
                "status": "VISION_UNAVAILABLE",
                "emotion": "UNKNOWN",
                "confidence": None,
                "reason": self._unavailable_reason,
            }

        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascades["face"].detectMultiScale(gray, 1.1, 5)
        if len(faces) == 0:
            return {**base, "status": "NO_FACE_DETECTED", "emotion": "UNKNOWN", "confidence": None}

        (x, y, w, h) = faces[0]
        roi_gray = gray[y : y + h, x : x + w]
        smiles = cascades["smile"].detectMultiScale(roi_gray, scaleFactor=1.7, minNeighbors=20)
        eyes = cascades["eye"].detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=5)

        if len(smiles) > 0:
            emotion, confidence = "HAPPY", 0.94
        elif len(eyes) < 2:
            emotion, confidence = "TIRED", 0.85
        else:
            std_dev = float(np.std(roi_gray))
            emotion, confidence = ("STRESSED", 0.87) if std_dev > 65.0 else ("CALM", 0.90)

        return {
            **base,
            "status": "FACE_ANALYZED",
            "emotion": emotion,
            "confidence": confidence,
            "face_detected": True,
            "bbox": [int(x), int(y), int(w), int(h)],
            "landmarks": {"smiles_count": int(len(smiles)), "eyes_count": int(len(eyes))},
        }


emotion_service = EmotionService()
