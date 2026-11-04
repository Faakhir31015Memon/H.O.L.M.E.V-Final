"""Navigation tool: it reports the routing server's answer, including "no answer"."""

from typing import Any

from pydantic import BaseModel, Field

from app.navigation.route_engine import route_engine
from app.tools.base import BaseTool, ToolResult


class NavigationRouteInput(BaseModel):
    destination: str = Field(default="", description="Target place name, or \"lat,lon\"")
    origin: str | None = Field(default=None, description="Start place name or \"lat,lon\"; empty means Home")


class NavigationRouteTool(BaseTool):
    name = "navigation.get_route"
    description = "Asks the configured routing server for road directions and a 3D path for the display."
    category = "navigation"
    permission_level = 1
    input_schema = NavigationRouteInput

    async def _run(self, destination: str = "", origin: str | None = None, **kwargs: Any) -> ToolResult:
        res = await route_engine.calculate_road_route(destination=destination, origin=origin)
        if not res.get("success"):
            return ToolResult(
                success=False,
                verified=False,
                data={
                    key: value
                    for key, value in res.items()
                    if key in ("action_required", "origin", "destination", "question", "source")
                },
                error=str(res.get("reason") or res.get("question") or "no route was produced"),
            )

        # The engine read the geometry off a live routing response; the 3D path is
        # that geometry, so it is as trustworthy as the server named in `source`.
        return ToolResult(success=True, verified=False, data=res)
