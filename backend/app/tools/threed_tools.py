"""3D tools: they generate geometry and files, and report what came back.

`verified` is left False on purpose. The verification engine decides - for exports it
stats the file the manager claims to have written, and for scene edits it reads the
manager back, which is a source outside the tool's own reply.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.projects.threed_manager import PRIMITIVES, threed_manager
from app.tools.base import BaseTool, ToolResult

_TYPE_HELP = ", ".join(PRIMITIVES)


def _vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return numbers if len(numbers) == 3 else None


class Create3DObjectInput(BaseModel):
    object_type: str = Field(description=f"Primitive to generate: {_TYPE_HELP}")
    position: list | None = Field(default=None, description="[x, y, z] centre of the object")
    scale: list | None = Field(default=None, description="[sx, sy, sz] size multipliers")
    color: str = Field(default="#00f0ff", description="Hex colour for the HUD material")


class Create3DObjectTool(BaseTool):
    name = "threed.create_object"
    description = "Generates a 3D primitive mesh in the scene and returns its real vertex and face counts."
    category = "3d"
    permission_level = 1
    input_schema = Create3DObjectInput

    async def _run(
        self, object_type: str = "cube", position: list | None = None,
        scale: list | None = None, color: str = "#00f0ff", **kwargs: Any
    ) -> ToolResult:
        try:
            obj = threed_manager.create_object(
                object_type=object_type,
                position=_vector(position),
                scale=_vector(scale) or [1, 1, 1],
                color=color,
            )
        except ValueError as exc:
            return ToolResult(success=False, verified=False, error=str(exc))

        return ToolResult(success=True, verified=False, data={"object": obj, "scene": threed_manager.scene_summary()})


class Transform3DObjectInput(BaseModel):
    object_id: str | None = Field(default=None, description="Object id; empty means the currently selected object")
    position: list | None = Field(default=None, description="[x, y, z] translation added to the current position")
    rotation: list | None = Field(default=None, description="[rx, ry, rz] degrees added to the current rotation")
    scale: list | None = Field(default=None, description="[sx, sy, sz] multiplied into the current scale")


class Transform3DObjectTool(BaseTool):
    name = "threed.transform_object"
    description = "Moves, rotates or scales one object in the scene."
    category = "3d"
    permission_level = 1
    input_schema = Transform3DObjectInput

    async def _run(
        self, object_id: str | None = None, position: list | None = None,
        rotation: list | None = None, scale: list | None = None, **kwargs: Any
    ) -> ToolResult:
        if object_id is None and position is None and rotation is None and scale is None:
            return ToolResult(success=False, verified=False, error="nothing was asked to change")

        updated, error = threed_manager.transform_object(
            object_id=object_id,
            position=_vector(position),
            rotation=_vector(rotation),
            scale=_vector(scale),
        )
        if error or updated is None:
            return ToolResult(success=False, verified=False, error=error or "the object could not be resolved")
        return ToolResult(success=True, verified=False, data={"object": updated})


class Delete3DObjectInput(BaseModel):
    object_id: str = Field(description="Id of the object to remove from the scene")


class Delete3DObjectTool(BaseTool):
    name = "threed.delete_object"
    description = "Removes an object from the 3D scene."
    category = "3d"
    permission_level = 1
    input_schema = Delete3DObjectInput

    async def _run(self, object_id: str = "", **kwargs: Any) -> ToolResult:
        _removed, error = threed_manager.delete_object(object_id)
        if error:
            return ToolResult(success=False, verified=False, error=error)
        summary = threed_manager.scene_summary()
        return ToolResult(success=True, verified=False, data={"deleted": object_id, "scene": summary})


class SceneInput(BaseModel):
    pass


class Read3DSceneTool(BaseTool):
    name = "threed.read_scene"
    description = "Lists the objects currently in the 3D scene with their transforms and mesh counts."
    category = "3d"
    permission_level = 0
    input_schema = SceneInput

    async def _run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=True,
            verified=False,
            data={
                "objects": threed_manager.get_scene(),
                "scene": threed_manager.scene_summary(),
                "bounding_box": threed_manager.bounding_box(),
            },
        )


class Export3DModelInput(BaseModel):
    format: str = Field(default="obj", description="Export container: obj or stl")
    folder_path: str = Field(default="3d", description="Workspace folder to write into")
    name: str = Field(default="scene", description="File stem")


class Export3DModelTool(BaseTool):
    name = "threed.export_model"
    description = "Writes the current scene to a real .obj or .stl file inside the workspace."
    category = "3d"
    permission_level = 1
    input_schema = Export3DModelInput

    async def _run(
        self, format: str = "obj", folder_path: str = "3d", name: str = "scene", **kwargs: Any
    ) -> ToolResult:
        chosen = (format or "obj").lower().lstrip(".")
        if chosen not in ("obj", "stl"):
            return ToolResult(success=False, verified=False, error=f"'{format}' is not a format this engine writes")

        try:
            result = (
                threed_manager.export_obj(folder_path=folder_path, name=name)
                if chosen == "obj"
                else threed_manager.export_stl(folder_path=folder_path, name=name)
            )
        except ValueError as exc:
            return ToolResult(success=False, verified=False, error=str(exc))

        if not result.get("written"):
            return ToolResult(success=False, verified=False, data=result, error=result.get("reason"))

        # The path travels under `path` so the verification engine can stat it; that
        # check, not this line, is what makes the export verified.
        return ToolResult(success=True, verified=False, data=result)


class SendToDisplayInput(BaseModel):
    content_type: str = Field(default="3d_scene", description="What is being sent")
    target_display_id: str | None = Field(default="projector_3d", description="Display entry to route to")


class SendToDisplayTool(BaseTool):
    name = "threed.send_to_display"
    description = "Routes the scene geometry to a configured external display entry."
    category = "3d"
    permission_level = 2
    input_schema = SendToDisplayInput

    async def _run(
        self, content_type: str = "3d_scene", target_display_id: str | None = "projector_3d", **kwargs: Any
    ) -> ToolResult:
        from app.displays.external_display_router import external_display_router

        payload = threed_manager.hologram_payload()
        res = external_display_router.route_content(content_type, payload, target_display_id=target_display_id)
        return ToolResult(
            success=bool(res.get("success")),
            verified=False,
            data=res,
            error=None if res.get("success") else "the display router refused",
        )
