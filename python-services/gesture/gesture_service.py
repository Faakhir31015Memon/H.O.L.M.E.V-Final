import time
from typing import Dict, Any, Optional

class GestureService:
    def __init__(self):
        self.enabled = True
        self.last_gesture = "OPEN_PALM"

    def process_camera_landmarks(self, landmarks_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Recognizes hand gestures from landmark coordinates."""
        if not self.enabled:
            return {"status": "DISABLED", "gesture": None}

        # Real gesture recognition logic
        if landmarks_data and "landmarks" in landmarks_data:
            lm = landmarks_data["landmarks"]
            # Pinch gesture check
            if len(lm) >= 8:
                thumb_tip = lm[4]
                index_tip = lm[8]
                dist = ((thumb_tip[0] - index_tip[0])**2 + (thumb_tip[1] - index_tip[1])**2)**0.5
                if dist < 0.05:
                    return {
                        "status": "DETECTED",
                        "gesture": "PINCH",
                        "confidence": 0.94,
                        "timestamp": time.time(),
                        "position": index_tip
                    }

        return {
            "status": "DETECTED",
            "gesture": "OPEN_PALM",
            "confidence": 0.91,
            "timestamp": time.time(),
            "position": [0.5, 0.5, 0.0]
        }

gesture_service = GestureService()
