import logging
from typing import Any

logger = logging.getLogger("holmev.displays.router")


class ExternalDisplayRouter:
    """Routes content between the displays the user has declared in configuration.

    Nothing here enumerates screens, so no entry claims to have detected one:
    `configured` is a fact about this list, and `probed` says plainly that the
    hardware was never asked.
    """

    def __init__(self):
        self.active_displays = [
            {"id": "primary_hud", "name": "Main HOLMEV HUD", "type": "PRIMARY", "configured": True},
            {"id": "projector_3d", "name": "3D Holographic Projector", "type": "PROJECTOR", "configured": True},
            {"id": "laptop_screen", "name": "Secondary Monitor / Laptop", "type": "MONITOR", "configured": True},
        ]
        self.active_routes: dict[str, dict[str, Any]] = {}

    def route_content(
        self, content_type: str, payload: dict[str, Any], target_display_id: str | None = "projector_3d"
    ) -> dict[str, Any]:
        display = next((d for d in self.active_displays if d["id"] == target_display_id), self.active_displays[1])

        route_entry = {
            "content_type": content_type,
            "payload": payload,
            "display_id": display["id"],
            "display_name": display["name"],
            "status": "ROUTED",
            "probed": False,
        }
        self.active_routes[content_type] = route_entry

        logger.info("Routed 3D content %s to display entry: %s", content_type, display["name"])

        return {
            "success": True,
            "content_type": content_type,
            "target_display": display,
            "probed": False,
            "note": "the display list is configuration, not detected hardware",
            "spoken_response": (
                f"3D {content_type} ko {display['name']} par bhejne ke liye route kar diya gaya, Boss. "
                "Asl mein screen judge hoti dikhai nahi di - configuration ke mutabiq route hua hai."
            ),
        }


external_display_router = ExternalDisplayRouter()
