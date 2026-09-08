from typing import Dict, Any, Optional
import logging

logger = logging.getLogger("holmev.displays.router")

class ExternalDisplayRouter:
    def __init__(self):
        self.active_displays = [
            {"id": "primary_hud", "name": "Main HOLMEV HUD", "type": "PRIMARY", "connected": True},
            {"id": "projector_3d", "name": "3D Holographic Projector", "type": "PROJECTOR", "connected": True},
            {"id": "laptop_screen", "name": "Secondary Monitor / Laptop", "type": "MONITOR", "connected": True}
        ]
        self.active_routes = {}

    def route_content(self, content_type: str, payload: Dict[str, Any], target_display_id: Optional[str] = "projector_3d") -> Dict[str, Any]:
        """
        Routes 3D Holographic circuits, 3D models, or 3D navigation layouts to external display/projector.
        """
        display = next((d for d in self.active_displays if d["id"] == target_display_id), self.active_displays[1])
        
        route_entry = {
            "content_type": content_type,
            "payload": payload,
            "display_id": display["id"],
            "display_name": display["name"],
            "status": "STREAMING"
        }
        self.active_routes[content_type] = route_entry

        logger.info(f"Routed 3D content {content_type} to external display: {display['name']}")

        return {
            "success": True,
            "content_type": content_type,
            "target_display": display,
            "spoken_response": f"3D {content_type} ko {display['name']} par projection ke liye route kar diya gaya hai, Boss."
        }

external_display_router = ExternalDisplayRouter()
