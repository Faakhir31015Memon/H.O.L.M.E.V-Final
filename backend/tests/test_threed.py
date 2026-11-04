"""3D tests: geometry is counted, exports are stat-ed, and no fake projector exists.

The scene manager is a module singleton, so every test starts from a clean scene.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

from app.projects.threed_manager import PRIMITIVES, ThreeDManager, threed_manager
from app.tools.registry import tool_registry


@pytest.fixture
def workspace(isolated_workspace: Path) -> Path:
    return isolated_workspace


@pytest.fixture
def clean_scene():
    """Hand out the singleton with an empty scene, and leave it empty afterwards."""

    threed_manager.objects.clear()
    threed_manager.selected_object_id = None
    yield threed_manager
    threed_manager.objects.clear()
    threed_manager.selected_object_id = None


@pytest.mark.parametrize("object_type", PRIMITIVES)
def test_every_primitive_generates_real_geometry(clean_scene: ThreeDManager, object_type: str):
    obj = clean_scene.create_object(object_type)
    assert obj["vertices"] > 0 and obj["faces"] > 0

    mesh = clean_scene.mesh_for(object_type)
    assert len(mesh["vertices"]) == obj["vertices"]
    for face in mesh["faces"]:
        assert all(1 <= index <= obj["vertices"] for index in face), "every face points at a real vertex"


def test_an_unknown_primitive_is_refused_with_the_actual_list(clean_scene: ThreeDManager):
    with pytest.raises(ValueError, match="not a primitive"):
        clean_scene.create_object("dodecahedron")


def test_transforms_compose_on_the_selected_object(clean_scene: ThreeDManager):
    clean_scene.create_object("cube", position=[1, 0, 0])

    moved, error = clean_scene.transform_object(position=[0, 2, 0])
    assert error is None
    assert moved["position"] == [1.0, 2.0, 0.0]

    clean_scene.transform_object(rotation=[0, 90, 0])
    scaled, _ = clean_scene.transform_object(scale=[2, 1, 1])
    assert scaled["scale"] == [2.0, 1.0, 1.0]
    assert scaled["rotation"] == [0.0, 90.0, 0.0]


def test_an_object_id_that_is_not_in_the_scene_is_named_back(clean_scene: ThreeDManager):
    clean_scene.create_object("cube")
    obj, error = clean_scene.transform_object(object_id="obj_missing", position=[1, 0, 0])
    assert obj is None
    assert "obj_missing" in error
    assert clean_scene.get_scene()[0]["position"] == [0.0, 0.0, 0.0], "the wrong object stayed put"


def test_a_transform_without_a_selection_refuses(clean_scene: ThreeDManager):
    obj, error = clean_scene.transform_object(position=[1, 1, 1])
    assert obj is None
    assert "no object was named" in error


def test_rotation_and_scale_reach_the_exported_vertices(clean_scene: ThreeDManager):
    clean_scene.create_object("cube", position=[0, 0, 0], scale=[2, 2, 2])
    vertices = clean_scene.transformed_vertices(clean_scene.get_scene()[0])
    assert max(abs(vertex[0]) for vertex in vertices) == pytest.approx(1.0)

    clean_scene.transform_object(rotation=[0, 0, 45])
    rotated = clean_scene.transformed_vertices(clean_scene.get_scene()[0])
    # A 45 degree turn keeps the corner distance but moves it off the axis.
    assert max(abs(vertex[0]) for vertex in rotated) == pytest.approx(1.4142135, abs=1e-5)

    box = clean_scene.bounding_box()
    assert box["empty"] is False
    assert len(box["size"]) == 3


def test_obj_export_writes_a_file_the_filesystem_agrees_with(clean_scene: ThreeDManager, workspace: Path):
    clean_scene.create_object("sphere")
    result = clean_scene.export_obj(folder_path="models", name="boss_scene")

    assert result["written"] is True
    path = Path(result["path"])
    assert path.is_file()
    assert path.stat().st_size == result["bytes"]

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# H.O.L.M.E.V scene export")
    vertex_lines = [line for line in text.splitlines() if line.startswith("v ")]
    face_lines = [line for line in text.splitlines() if line.startswith("f ")]
    assert len(vertex_lines) == clean_scene.get_scene()[0]["vertices"]
    assert len(face_lines) == clean_scene.get_scene()[0]["faces"]
    assert all(re.fullmatch(r"f(?: \d+){3,}", line) for line in face_lines), "faces reference vertices 1-based"


def test_stl_export_is_a_readable_binary_stl(clean_scene: ThreeDManager, workspace: Path):
    clean_scene.create_object("cube")
    result = clean_scene.export_stl(folder_path="models", name="part")

    raw = Path(result["path"]).read_bytes()
    assert len(raw) == 84 + result["triangles"] * 50

    (count,) = struct.unpack("<I", raw[80:84])
    assert count == result["triangles"] == 12

    normal_x, normal_y, normal_z = struct.unpack("<3f", raw[84:96])
    assert abs(normal_x**2 + normal_y**2 + normal_z**2 - 1.0) < 1e-5


def test_an_export_cannot_escape_the_workspace(clean_scene: ThreeDManager, workspace: Path):
    clean_scene.create_object("cube")
    with pytest.raises(ValueError, match="guard"):
        clean_scene.export_obj(folder_path="../../outside", name="sneaky")
    assert not (workspace.parent / "outside").exists()


def test_an_empty_scene_exports_nothing(clean_scene: ThreeDManager):
    assert clean_scene.export_obj()["written"] is False
    assert clean_scene.export_stl()["written"] is False


def test_hologram_payload_admits_that_no_projector_was_seen(clean_scene: ThreeDManager):
    clean_scene.create_object("cone")
    payload = clean_scene.hologram_payload(path_points=[[0, 0, 0], [1, 0, 1]])
    assert payload["path"] == [[0, 0, 0], [1, 0, 1]]
    assert "no projector" in payload["hardware_note"]


@pytest.mark.asyncio
async def test_creating_through_the_tool_leaves_verified_to_the_engine():
    tool = tool_registry.get_tool("threed.create_object")
    result = await tool.execute(object_type="cube", position=[0, 0, 0])
    assert result.success is True
    assert result.verified is False, "a tool may not verify itself"
    assert result.data["object"]["vertices"] == 8


@pytest.mark.asyncio
async def test_the_tool_refuses_a_primitive_the_engine_cannot_build():
    tool = tool_registry.get_tool("threed.create_object")
    result = await tool.execute(object_type="pyramid")
    assert result.success is False
    assert "cube" in result.error


@pytest.mark.asyncio
async def test_transform_of_a_missing_object_reports_the_truth(clean_scene: ThreeDManager):
    tool = tool_registry.get_tool("threed.transform_object")
    result = await tool.execute(object_id="obj_missing", position=[1, 0, 0])
    assert result.success is False
    assert "no object was named" in result.error or "not in this scene" in result.error


@pytest.mark.asyncio
async def test_exporting_reports_the_path_and_the_tool_still_does_not_self_verify(
    clean_scene: ThreeDManager, workspace: Path
):
    create = tool_registry.get_tool("threed.create_object")
    await create.execute(object_type="cylinder")

    export = tool_registry.get_tool("threed.export_model")
    result = await export.execute(format="obj", folder_path="exports", name="model")
    assert result.success is True
    assert result.verified is False
    assert Path(result.data["path"]).is_file()

    read = tool_registry.get_tool("threed.read_scene")
    scene = await read.execute()
    assert scene.data["scene"]["objects"] == 1


@pytest.mark.asyncio
async def test_sending_to_a_display_reports_configuration_not_sight(clean_scene: ThreeDManager):
    clean_scene.create_object("plane")
    tool = tool_registry.get_tool("threed.send_to_display")
    result = await tool.execute(content_type="3d_scene", target_display_id="projector_3d")

    assert result.success is True
    assert result.verified is False
    assert result.data["probed"] is False
    assert result.data["target_display"]["configured"] is True
