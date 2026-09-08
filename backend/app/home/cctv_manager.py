import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("holmev.cctv")

class CCTVCameraManager:
    def __init__(self):
        # Default registered cameras in H.O.L.M.E.V ecosystem
        self.cameras: Dict[str, Dict[str, Any]] = {
            "bedroom": {"id": "cam_01", "name": "Bedroom Camera", "status": "ONLINE", "stream_url": "/api/cctv/stream/bedroom"},
            "hall": {"id": "cam_02", "name": "Hall Camera", "status": "ONLINE", "stream_url": "/api/cctv/stream/hall"},
            "kitchen": {"id": "cam_03", "name": "Kitchen Camera", "status": "ONLINE", "stream_url": "/api/cctv/stream/kitchen"},
            "entrance": {"id": "cam_04", "name": "Main Entrance Camera", "status": "ONLINE", "stream_url": "/api/cctv/stream/entrance"},
            "office": {"id": "cam_05", "name": "Office Room Camera", "status": "ONLINE", "stream_url": "/api/cctv/stream/office"}
        }

    def process_camera_request(self, camera_names: Optional[List[str]] = None, raw_query: str = "") -> Dict[str, Any]:
        """
        Processes camera display requests.
        If camera_names is empty or ambiguous, prompts user for selection.
        Supports single or multi-camera selection (e.g., ['bedroom', 'hall']).
        """
        if not camera_names:
            query_lower = raw_query.lower() if raw_query else ""
            detected = []
            for key in self.cameras.keys():
                if key in query_lower:
                    detected.append(key)
            if detected:
                camera_names = detected

        if not camera_names:
            available_names = [cam["name"] for cam in self.cameras.values()]
            return {
                "success": True,
                "action_required": "DISAMBIGUATION_NEEDED",
                "question": "Aap ke ghar mein 5 cameras connected hain. Konsa wala camera dikhaoon? (e.g. Bedroom, Hall, ya dono?)",
                "available_cameras": available_names,
                "active_streams": []
            }

        selected_streams = []
        for name in camera_names:
            key = name.lower().strip()
            if key in self.cameras:
                selected_streams.append(self.cameras[key])

        if not selected_streams:
            return {
                "success": False,
                "error": f"Maaf kijiye Boss, camera '{', '.join(camera_names)}' nahi mila.",
                "active_streams": []
            }

        stream_titles = " aur ".join([s["name"] for s in selected_streams])
        return {
            "success": True,
            "action_required": "DISPLAY_FEED",
            "message": f"{stream_titles} display kar diya gaya hai.",
            "mode": "MULTI_VIEW" if len(selected_streams) > 1 else "SINGLE_VIEW",
            "active_streams": selected_streams
        }

cctv_manager = CCTVCameraManager()
