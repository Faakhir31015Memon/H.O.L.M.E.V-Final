from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult

class Create3DObjectInput(BaseModel):
    object_type: str = Field(description="3D object primitive type: cube, sphere, cylinder, plane, cone")
    position: Optional[list] = Field(default=[0, 0, 0], description="[x, y, z] position coordinates")
    color: Optional[str] = Field(default="#00f0ff", description="Hex color string")

class Create3DObjectTool(BaseTool):
    name = "threed.create_object"
    description = "Creates a 3D object mesh primitive in the 3D workspace."
    category = "3d"
    permission_level = 1
    input_schema = Create3DObjectInput

    async def _run(self, object_type: str, position: list = [0, 0, 0], color: str = "#00f0ff") -> ToolResult:
        from app.projects.threed_manager import threed_manager
        
        obj = threed_manager.create_object(object_type=object_type, position=position, color=color)
        return ToolResult(
            success=True,
            verified=True,
            data={"object": obj},
            error=None
        )

class Transform3DObjectInput(BaseModel):
    object_id: Optional[str] = Field(default=None, description="Object ID or use currently selected object if None")
    position: Optional[list] = Field(default=None, description="[x, y, z] translation delta or position")
    scale: Optional[list] = Field(default=None, description="[sx, sy, sz] scale factors")

class Transform3DObjectTool(BaseTool):
    name = "threed.transform_object"
    description = "Moves, scales, or rotates a 3D object in the workspace."
    category = "3d"
    permission_level = 1
    input_schema = Transform3DObjectInput

    async def _run(self, object_id: Optional[str] = None, position: Optional[list] = None, scale: Optional[list] = None) -> ToolResult:
        from app.projects.threed_manager import threed_manager
        
        updated_obj, err = threed_manager.transform_object(object_id=object_id, position=position, scale=scale)
        if err:
            return ToolResult(success=False, verified=False, error=err)
        return ToolResult(success=True, verified=True, data={"object": updated_obj}, error=None)
