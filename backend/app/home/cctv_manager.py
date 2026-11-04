"""Which cameras the user declared, and what was actually proven about them.

A security-camera list that says "ONLINE" without ever touching a stream is worse
than useless - it teaches the user to trust a light that was never a light. So:

* rooms come from `CAMERA_LABELS`, and `CAMERAS` in `.env` may attach a real URL;
* an entry without a URL says `has_feed: False` instead of pretending;
* `probe()` is the only thing that can call a feed ONLINE, and it is never run at
  import or on a voice request - someone has to ask for it;
* an RTSP URL is reported as not probeable from here rather than guessed at.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger("holmev.cctv")

CAMERA_LABELS = {
    "bedroom": ("cam_01", "Bedroom Camera"),
    "hall": ("cam_02", "Hall Camera"),
    "kitchen": ("cam_03", "Kitchen Camera"),
    "entrance": ("cam_04", "Main Entrance Camera"),
    "office": ("cam_05", "Office Room Camera"),
}


def declared_urls() -> dict[str, str]:
    """The room to stream-URL map from configuration; malformed JSON is not silently eaten."""

    raw = (settings.CAMERAS or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("CAMERAS is not valid JSON: %s", exc)
        return {"_error": f"CAMERAS is not valid JSON: {exc.msg}"}
    if not isinstance(parsed, dict):
        return {"_error": "CAMERAS must be a JSON object of room to stream URL"}
    return {str(key).lower(): str(value) for key, value in parsed.items()}


class CCTVCameraManager:
    def __init__(self) -> None:
        self.cameras: dict[str, dict[str, Any]] = {}
        self.refresh()

    def refresh(self) -> dict[str, dict[str, Any]]:
        urls = declared_urls()
        self.cameras = {
            room: {
                "id": camera_id,
                "name": name,
                "configured": True,
                "stream_url": urls.get(room),
                "has_feed": bool(urls.get(room)),
                "feeds_verified": False,
                "status": "UNKNOWN",
            }
            for room, (camera_id, name) in CAMERA_LABELS.items()
        }
        # A room the user declared that is not one of the five labels is still a camera.
        for room, url in urls.items():
            if room in ("_error",) or room in self.cameras:
                continue
            self.cameras[room] = {
                "id": f"cam_{room[:6]}",
                "name": room.title() + " Camera",
                "configured": True,
                "stream_url": url,
                "has_feed": bool(url),
                "feeds_verified": False,
                "status": "UNKNOWN",
            }
        return self.cameras

    def detect_rooms(self, raw_query: str) -> list[str]:
        query_lower = (raw_query or "").lower()
        return [room for room in self.cameras if room in query_lower]

    def process_camera_request(
        self, camera_names: list[str] | None = None, raw_query: str = ""
    ) -> dict[str, Any]:
        """Resolve which rooms the user meant, or ask once instead of guessing.

        Ambiguity is answered with a question, never with a random camera - the
        point of this feature is that the user knows which room they are looking at.
        """

        if not camera_names:
            camera_names = self.detect_rooms(raw_query)

        if not camera_names:
            return {
                "success": True,
                "action_required": "DISAMBIGUATION_NEEDED",
                "question": (
                    f"Aap ke ghar mein {len(self.cameras)} cameras configure hain. "
                    "Konsa wala camera dikhaoon? (e.g. Bedroom, Hall, ya dono?)"
                ),
                "available_cameras": [camera["name"] for camera in self.cameras.values()],
                "active_streams": [],
            }

        selected = [self.cameras[name.lower().strip()] for name in camera_names if name.lower().strip() in self.cameras]
        unknown = [name for name in camera_names if name.lower().strip() not in self.cameras]
        if not selected:
            return {
                "success": False,
                "error": f"Maaf kijiye Boss, camera '{', '.join(camera_names)}' configure list mein nahi mila.",
                "active_streams": [],
            }

        titles = " aur ".join(camera["name"] for camera in selected)
        without_feed = [camera["name"] for camera in selected if not camera["has_feed"]]
        return {
            "success": True,
            "action_required": "DISPLAY_FEED",
            "message": (
                f"{titles} ka feed request UI ko de diya gaya hai."
                + (
                    f" In ka URL configure nahi hai: {', '.join(without_feed)}."
                    if without_feed
                    else ""
                )
            ),
            "mode": "MULTI_VIEW" if len(selected) > 1 else "SINGLE_VIEW",
            "active_streams": selected,
            "feeds_verified": False,
            "not_found": unknown,
            "note": "this routed the request; no camera stream was probed for a live picture",
        }

    async def probe(self, rooms: list[str] | None = None) -> dict[str, Any]:
        """Actually ask each HTTP feed whether it answers. The only path to ONLINE."""

        self.refresh()
        targets = rooms or list(self.cameras)
        results: dict[str, str] = {}

        for room in targets:
            camera = self.cameras.get(room.lower().strip())
            if camera is None:
                results[room] = "not a configured camera"
                continue
            url = camera.get("stream_url")
            if not url:
                camera["status"] = "NO_URL"
                results[room] = "no stream URL is configured for it"
                continue
            if not url.lower().startswith(("http://", "https://")):
                camera["status"] = "NOT_PROBEABLE"
                results[room] = f"{url.split('://')[0]} cannot be probed over HTTP from here"
                continue

            try:
                async with httpx.AsyncClient(timeout=settings.CAMERA_PROBE_TIMEOUT_S) as client:
                    response = await client.get(url, follow_redirects=True)
                camera["status"] = "ONLINE" if response.status_code < 400 else f"HTTP {response.status_code}"
                camera["feeds_verified"] = response.status_code < 400
                results[room] = camera["status"]
            except httpx.HTTPError as exc:
                camera["status"] = "OFFLINE"
                camera["feeds_verified"] = False
                results[room] = f"unreachable ({type(exc).__name__})"

        return {
            "probed": True,
            "results": results,
            "cameras": list(self.cameras.values()),
            "note": "status came from an HTTP request to the configured URL, made just now",
        }


cctv_manager = CCTVCameraManager()
