"""Navigation: a route comes from a routing engine or the answer is "no route".

The previous version printed "6.5 km, 12 mins" with four invented turn instructions
for any destination typed at it, and handed a made-up polyline to the 3D display.
A user who trusted that would have driven somewhere that did not exist.

Now this module talks to a real OSRM-compatible server (self-hosted or public) and a
real geocoder, and when neither is configured it returns the exact reason plus the
exact command that would fix it. Distances, durations and step instructions here are
always the numbers the routing server returned.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger("holmev.navigation")

REQUEST_TIMEOUT_S = 12.0
USER_AGENT = "H.O.L.M.E.V/1.0 (personal assistant; local routing)"


def routing_server() -> str:
    return (os.environ.get("OSRM_BASE_URL") or settings.OSRM_BASE_URL or "").strip().rstrip("/")


def geocoder_server() -> str:
    return (os.environ.get("NOMINATIM_BASE_URL") or settings.NOMINATIM_BASE_URL or "").strip().rstrip("/")


def _parse_pair(value: str) -> tuple[float, float] | None:
    """Accept "33.5891,73.0421" so a route works with no geocoder at all."""

    parts = [part.strip() for part in value.replace(";", ",").split(",")]
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


def _hologram_path(coordinates: list[list[float]]) -> list[list[float]]:
    """Project the real geometry into local x/z metres for the 3D display.

    A tiny 3-degree bounding box is scaled into a 100-unit plane; the shape is the
    road the engine returned, not a decorative line.
    """

    if len(coordinates) < 2:
        return [[0.0, 0.0, 0.0]]
    lons = [point[0] for point in coordinates]
    lats = [point[1] for point in coordinates]
    span_lon = max(1e-9, max(lons) - min(lons))
    span_lat = max(1e-9, max(lats) - min(lats))
    step = max(1, len(coordinates) // 40)
    return [
        [round((point[0] - min(lons)) / span_lon * 100, 2), 0.0, round((point[1] - min(lats)) / span_lat * 100, 2)]
        for point in coordinates[::step]
    ]


def _humanise(step: dict[str, Any]) -> str:
    maneuver = step.get("maneuver") or {}
    kind = str(maneuver.get("type") or "")
    modifier = str(maneuver.get("modifier") or "")
    road = str(step.get("name") or "").strip()
    onto = f" onto {road}" if road else ""
    if kind == "depart":
        return f"Head out{onto or ' from your starting point'}"
    if kind == "arrive":
        return f"Arrive{onto}"
    if kind == "turn":
        return f"Turn {modifier or 'ahead'}{onto}"
    if kind in ("new name", "merge", "on ramp", "off ramp", "fork", "end of road", "roundabout", "continue"):
        return f"{kind.title()} {modifier}{onto}".strip()
    return f"{kind.title()} {modifier}".strip() + onto


class RouteEngine:
    def __init__(self) -> None:
        self.missing_map_hint = (
            "No routing server is configured, so this assistant cannot know how far anything is. "
            "Run one locally with `docker run -t -p 5000:5000 osrm/osrm-backend osrm-routed "
            "--algorithm mml /data/map.osrm` and set OSRM_BASE_URL=http://127.0.0.1:5000, or point "
            "OSRM_BASE_URL at a server you trust. NOMINATIM_BASE_URL is needed to turn a place name "
            'into coordinates; otherwise pass "lat,lon".'
        )

    @property
    def is_configured(self) -> bool:
        return bool(routing_server())

    async def _resolve(self, query: str) -> dict[str, Any]:
        pair = _parse_pair(query)
        if pair is not None:
            return {"ok": True, "lat": pair[0], "lon": pair[1], "label": query, "via": "coordinates"}

        base = geocoder_server()
        if not base:
            return {
                "ok": False,
                "reason": f"'{query}' is a place name and no geocoder is configured, so it has no coordinates here.",
                "action_required": "GEOCODER_MISSING",
            }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get(
                    f"{base}/search",
                    params={"q": query, "format": "jsonv2", "limit": 1},
                )
                response.raise_for_status()
                found = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "reason": f"the geocoder did not answer for '{query}': {type(exc).__name__}"}

        if not found:
            return {"ok": False, "reason": f"the geocoder has no match for '{query}'", "action_required": "NO_MATCH"}
        place = found[0]
        return {
            "ok": True,
            "lat": float(place["lat"]),
            "lon": float(place["lon"]),
            "label": str(place.get("display_name") or query),
            "via": "geocoder",
        }

    async def calculate_road_route(self, destination: str, origin: str | None = None) -> dict[str, Any]:
        """Ask the routing server for the way, and report only what it said."""

        if not (destination or "").strip():
            return {
                "success": False,
                "action_required": "DESTINATION_NEEDED",
                "question": "Aap ko kahan jana hai Boss? Destination batayein.",
                "route": None,
            }

        if not self.is_configured:
            return {
                "success": False,
                "action_required": "MAP_BACKEND_MISSING",
                "reason": self.missing_map_hint,
                "route": None,
            }

        start_label = (origin or "").strip()
        if start_label:
            start = await self._resolve(start_label)
        elif settings.HOME_LATITUDE or settings.HOME_LONGITUDE:
            start = {
                "ok": True,
                "lat": settings.HOME_LATITUDE,
                "lon": settings.HOME_LONGITUDE,
                "label": "Home",
                "via": "configured_home",
            }
        else:
            start = {
                "ok": False,
                "action_required": "ORIGIN_UNKNOWN",
                "reason": (
                    "no starting point is known: this PC has no location source, HOME_LATITUDE/HOME_LONGITUDE "
                    "are unset, and the request did not name an origin."
                ),
            }

        end = await self._resolve(destination)
        if not start.get("ok") or not end.get("ok"):
            missing = end if not end.get("ok") else start
            return {
                "success": False,
                "action_required": str(missing.get("action_required") or "ROUTE_NOT_FOUND"),
                "reason": str(missing.get("reason")),
                "route": None,
            }

        base = routing_server()
        url = f"{base}/route/v1/driving/{start['lon']},{start['lat']};{end['lon']},{end['lat']}"
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get(url, params={"overview": "full", "geometries": "geojson", "steps": "true"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "success": False,
                "action_required": "ROUTE_SERVER_FAILED",
                "reason": f"the routing server at {base} did not answer: {type(exc).__name__}: {exc}"[:200],
                "route": None,
            }

        if payload.get("code") != "Ok" or not payload.get("routes"):
            return {
                "success": False,
                "action_required": "NO_ROUTE",
                "reason": f"the routing server has no road between those points (code={payload.get('code')})",
                "route": None,
            }

        route = payload["routes"][0]
        metres = float(route.get("distance") or 0.0)
        seconds = float(route.get("duration") or 0.0)
        raw_steps = (route.get("legs") or [{}])[0].get("steps") or []
        steps = [
            {
                "step": index,
                "instruction": _humanise(step),
                "distance": _distance(step.get("distance")),
                "action": str((step.get("maneuver") or {}).get("type") or "").upper(),
            }
            for index, step in enumerate(raw_steps, start=1)
        ]

        return {
            "success": True,
            "origin": start.get("label") or f"{start['lat']},{start['lon']}",
            "destination": end.get("label") or destination,
            "total_distance": _distance(metres),
            "estimated_time": _duration(seconds),
            "steps": steps,
            "hologram_path_3d": _hologram_path(((route.get("geometry") or {}).get("coordinates")) or []),
            "source": base,
            "spoken_response": (
                f"Boss, {start.get('label')} se {end.get('label')} {_distance(metres)} hai "
                f"(~{_duration(seconds)}), {base} se liya hua rasta."
            ),
        }

    @staticmethod
    def current_location() -> str:
        return (
            "not known: set HOME_LATITUDE/HOME_LONGITUDE in .env"
            if not (settings.HOME_LATITUDE or settings.HOME_LONGITUDE)
            else f"{settings.HOME_LATITUDE},{settings.HOME_LONGITUDE} (from .env)"
        )


def _distance(metres: Any) -> str:
    value = float(metres or 0.0)
    return f"{value / 1000:.1f} km" if value >= 1000 else f"{value:.0f} m"


def _duration(seconds: Any) -> str:
    minutes = round(float(seconds or 0.0) / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


route_engine = RouteEngine()
