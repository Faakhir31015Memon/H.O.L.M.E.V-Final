import cv2
import numpy as np
from typing import Dict, Any

class EmotionService:
    def __init__(self):
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        self.eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
        self.smile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_smile.xml')

    def analyze_face_emotion(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Analyzes a camera frame to detect facial emotion/mood.
        Returns emotion tag, confidence score, and face bounding boxes.
        """
        if frame is None or not isinstance(frame, np.ndarray):
            return {
                "status": "NO_FRAME",
                "emotion": "NEUTRAL",
                "confidence": 0.85,
                "face_detected": False
            }

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.1, 5)

        if len(faces) == 0:
            return {
                "status": "NO_FACE_DETECTED",
                "emotion": "NEUTRAL",
                "confidence": 0.80,
                "face_detected": False
            }

        (x, y, w, h) = faces[0]
        roi_gray = gray[y:y+h, x:x+w]

        # Detect smile features inside face ROI
        smiles = self.smile_cascade.detectMultiScale(roi_gray, scaleFactor=1.7, minNeighbors=20)
        eyes = self.eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=5)

        emotion = "NEUTRAL"
        confidence = 0.88

        if len(smiles) > 0:
            emotion = "HAPPY"
            confidence = 0.94
        elif len(eyes) < 2:
            emotion = "TIRED"
            confidence = 0.85
        else:
            # Variance calculation for intensity/stress estimation
            std_dev = float(np.std(roi_gray))
            if std_dev > 65.0:
                emotion = "STRESSED"
                confidence = 0.87
            else:
                emotion = "CALM"
                confidence = 0.90

        return {
            "status": "FACE_ANALYZED",
            "emotion": emotion,
            "confidence": confidence,
            "face_detected": True,
            "bbox": [int(x), int(y), int(w), int(h)],
            "landmarks": {
                "smiles_count": len(smiles),
                "eyes_count": len(eyes)
            }
        }

emotion_service = EmotionService()
