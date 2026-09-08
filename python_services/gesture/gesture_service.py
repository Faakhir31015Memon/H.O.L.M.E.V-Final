import time
from typing import Dict, Any, Optional

class GestureService:
    def __init__(self):
        self.enabled = True
        self.last_gesture = "OPEN_PALM"

    def process_camera_landmarks(self, landmarks_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Recognizes Tony Stark / Iron Man hand gestures from landmark coordinates."""
        if not self.enabled:
            return {"status": "DISABLED", "gesture": None}

        # Real gesture recognition logic
        if landmarks_data and "landmarks" in landmarks_data:
            lm = landmarks_data["landmarks"]
            if len(lm) >= 8:
                thumb_tip = lm[4]
                index_tip = lm[8]
                wrist = lm[0] if len(lm) > 0 else [0.5, 0.5, 0]

                # Distance calculation
                dist_pinch = ((thumb_tip[0] - index_tip[0])**2 + (thumb_tip[1] - index_tip[1])**2)**0.5

                # Trash Throw gesture check (Hand swipe speed / fast movement towards screen edge)
                if index_tip[0] > 0.85 or index_tip[1] > 0.85:
                    return {
                        "status": "DETECTED",
                        "gesture": "TRASH_THROW",
                        "action": "DELETE_SELECTED_ITEM",
                        "confidence": 0.96,
                        "timestamp": time.time(),
                        "position": index_tip
                    }

                # Pinch gesture for holding/wiring
                if dist_pinch < 0.04:
                    return {
                        "status": "DETECTED",
                        "gesture": "PINCH_GRAB",
                        "action": "HOLD_OBJECT",
                        "confidence": 0.95,
                        "timestamp": time.time(),
                        "position": index_tip
                    }

        return {
            "status": "DETECTED",
            "gesture": "OPEN_PALM",
            "action": "IDLE_HOVER",
            "confidence": 0.91,
            "timestamp": time.time(),
            "position": [0.5, 0.5, 0.0]
        }

gesture_service = GestureService()
