from typing import Optional, Any
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult
from app.navigation.route_engine import route_engine

class NavigationRouteInput(BaseModel):
    destination: str = Field(default="", description="Target destination place or address")
    origin: Optional[str] = Field(default=None, description="Starting point or current location")

class NavigationRouteTool(BaseTool):
    name = "navigation.get_route"
    description = "Calculates road directions and displays 3D holographic navigation map to target location."
    category = "navigation"
    permission_level = 1
    input_schema = NavigationRouteInput

    async def _run(self, destination: str = "", origin: Optional[str] = None, **kwargs: Any) -> ToolResult:
        res = route_engine.calculate_road_route(destination=destination, origin=origin)
        return ToolResult(
            success=res["success"],
            verified=True,
            data=res,
            error=None if res["success"] else res.get("question")
        )
