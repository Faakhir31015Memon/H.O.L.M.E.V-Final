"""3D scene engine: real geometry, real files, no imagined hardware.

This is the part of the 3D feature that can be truthfully claimed on a PC with no
holographic projector:

* primitives are generated as vertex/face meshes (counts are computed, not declared);
* transforms compose in the order scale -> rotate -> translate, like every viewer
  the user might open the export in;
* exports are genuine Wavefront OBJ and binary STL files written inside the
  workspace, so the verification engine can prove they exist by stat-ing them;
* the projector router is asked, and its answer (configuration, not detected
  hardware) is what gets reported back.

Nothing here reports that a beam of light exists.
"""

from __future__ import annotations

import math
import os
import struct
import uuid
from pathlib import Path
from typing import Any

from app.security.path_guard import PathRejected, guard, workspace_root

PRIMITIVES = ("cube", "sphere", "cylinder", "cone", "plane", "torus")
MAX_OBJECTS = 200
Mesh = dict[str, list[Any]]


def _cube() -> Mesh:
    s = 0.5
    return {
        "vertices": [
            [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
            [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s],
        ],
        "faces": [
            [1, 2, 3, 4], [8, 7, 6, 5], [4, 3, 7, 8], [2, 1, 5, 6], [3, 2, 6, 7], [4, 8, 5, 1]
        ],
    }


def _plane() -> Mesh:
    s = 0.5
    return {"vertices": [[-s, 0, -s], [s, 0, -s], [s, 0, s], [-s, 0, s]], "faces": [[1, 2, 3, 4]]}


def _sphere(segments: int = 16, rings: int = 8) -> Mesh:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        for segment in range(segments):
            theta = 2 * math.pi * segment / segments
            vertices.append(
                [
                    0.5 * math.sin(phi) * math.cos(theta),
                    0.5 * math.cos(phi),
                    0.5 * math.sin(phi) * math.sin(theta),
                ]
            )
    for ring in range(rings):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append(
                [
                    ring * segments + segment + 1,
                    ring * segments + next_segment + 1,
                    (ring + 1) * segments + next_segment + 1,
                    (ring + 1) * segments + segment + 1,
                ]
            )
    return {"vertices": vertices, "faces": faces}


def _cylinder(steps: int = 16) -> Mesh:
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for cap_y in (-0.5, 0.5):
        vertices.append([0.0, cap_y, 0.0])
    centre_bottom, centre_top = 1, 2
    for step in range(steps):
        angle = 2 * math.pi * step / steps
        vertices.append([0.5 * math.cos(angle), -0.5, 0.5 * math.sin(angle)])
    for step in range(steps):
        angle = 2 * math.pi * step / steps
        vertices.append([0.5 * math.cos(angle), 0.5, 0.5 * math.sin(angle)])
    ring_bottom = 3
    ring_top = 3 + steps
    for step in range(steps):
        next_step = (step + 1) % steps
        faces.append([ring_bottom + step, ring_bottom + next_step, ring_top + next_step, ring_top + step])
        faces.append([centre_bottom, ring_bottom + next_step, ring_bottom + step])
        faces.append([centre_top, ring_top + step, ring_top + next_step])
    return {"vertices": vertices, "faces": faces}


def _cone(steps: int = 16) -> Mesh:
    vertices: list[list[float]] = [[0.0, 0.5, 0.0], [0.0, -0.5, 0.0]]
    faces: list[list[int]] = []
    for step in range(steps):
        angle = 2 * math.pi * step / steps
        vertices.append([0.5 * math.cos(angle), -0.5, 0.5 * math.sin(angle)])
    base_start = 3
    for step in range(steps):
        next_step = (step + 1) % steps
        faces.append([1, base_start + step, base_start + next_step])
        faces.append([2, base_start + next_step, base_start + step])
    return {"vertices": vertices, "faces": faces}


def _torus(steps: int = 16, tube_steps: int = 10) -> Mesh:
    major, minor = 0.35, 0.15
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for i in range(steps):
        u = 2 * math.pi * i / steps
        for j in range(tube_steps):
            v = 2 * math.pi * j / tube_steps
            vertices.append(
                [
                    (major + minor * math.cos(v)) * math.cos(u),
                    minor * math.sin(v),
                    (major + minor * math.cos(v)) * math.sin(u),
                ]
            )
    for i in range(steps):
        for j in range(tube_steps):
            a = i * tube_steps + j + 1
            b = ((i + 1) % steps) * tube_steps + j + 1
            c = ((i + 1) % steps) * tube_steps + (j + 1) % tube_steps + 1
            d = i * tube_steps + (j + 1) % tube_steps + 1
            faces.append([a, b, c, d])
    return {"vertices": vertices, "faces": faces}


BUILDERS = {"cube": _cube, "plane": _plane, "sphere": _sphere, "cylinder": _cylinder, "cone": _cone, "torus": _torus}


def _rotate(point: list[float], euler_deg: list[float]) -> list[float]:
    x, y, z = point
    rx, ry, rz = (math.radians(float(angle)) for angle in euler_deg)

    cy, sy = math.cos(ry), math.sin(ry)
    x, z = cy * x + sy * z, -sy * x + cy * z
    cx, sx = math.cos(rx), math.sin(rx)
    y, z = cx * y - sx * z, sx * y + cx * z
    cz, sz = math.cos(rz), math.sin(rz)
    x, y = cz * x - sz * y, sz * x + cz * y
    return [x, y, z]


class ThreeDManager:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.selected_object_id: str | None = None
        self._meshes: dict[str, Mesh] = {}

    # ------------------------------------------------------------------ scene

    def mesh_for(self, object_type: str) -> Mesh:
        builder = BUILDERS.get(object_type)
        if builder is None:
            raise ValueError(
                f"'{object_type}' is not a primitive this engine can generate. Available: {', '.join(PRIMITIVES)}."
            )
        if object_type not in self._meshes:
            self._meshes[object_type] = builder()
        return self._meshes[object_type]

    def create_object(
        self, object_type: str, position: list[float] | None = None, color: str = "#00f0ff",
        scale: list[float] | None = None, rotation: list[float] | None = None
    ) -> dict[str, Any]:
        if len(self.objects) >= MAX_OBJECTS:
            raise ValueError(f"the scene already holds {MAX_OBJECTS} objects")

        mesh = self.mesh_for(object_type)
        obj_id = f"obj_{uuid.uuid4().hex[:8]}"
        obj_data = {
            "id": obj_id,
            "type": object_type,
            "position": [float(v) for v in (position or [0, 0, 0])],
            "rotation": [float(v) for v in (rotation or [0, 0, 0])],
            "scale": [float(v) for v in (scale or [1, 1, 1])],
            "color": color,
            "vertices": len(mesh["vertices"]),
            "faces": len(mesh["faces"]),
        }
        self.objects[obj_id] = obj_data
        self.selected_object_id = obj_id
        return obj_data

    def _target(self, object_id: str | None) -> tuple[dict[str, Any] | None, str | None]:
        """An unnamed transform applies to the selected object, never to a guess."""

        if object_id:
            obj = self.objects.get(object_id)
            return obj, (None if obj else f"'{object_id}' is not in this scene.")
        if self.selected_object_id:
            obj = self.objects.get(self.selected_object_id)
            return obj, (None if obj else f"'{self.selected_object_id}' is no longer in this scene.")
        return None, (
            "no object was named and the scene has no selection, so nothing was moved. "
            "Create an object or pass its id."
        )

    def transform_object(
        self, object_id: str | None = None, position: list[float] | None = None,
        scale: list[float] | None = None, rotation: list[float] | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        obj, error = self._target(object_id)
        if obj is None:
            return None, error

        if position:
            obj["position"] = [obj["position"][i] + float(position[i]) for i in range(3)]
        if rotation:
            obj["rotation"] = [obj["rotation"][i] + float(rotation[i]) for i in range(3)]
        if scale:
            obj["scale"] = [obj["scale"][i] * float(scale[i]) for i in range(3)]
        return obj, None

    def delete_object(self, object_id: str) -> tuple[bool, str | None]:
        if object_id not in self.objects:
            return False, f"'{object_id}' is not in this scene."
        del self.objects[object_id]
        if self.selected_object_id == object_id:
            self.selected_object_id = next(iter(self.objects), None)
        return True, None

    def get_scene(self) -> list[dict[str, Any]]:
        return list(self.objects.values())

    def scene_summary(self) -> dict[str, Any]:
        return {
            "objects": len(self.objects),
            "selected": self.selected_object_id,
            "total_vertices": sum(obj["vertices"] for obj in self.objects.values()),
            "total_faces": sum(obj["faces"] for obj in self.objects.values()),
            "types": sorted({obj["type"] for obj in self.objects.values()}),
        }

    # ------------------------------------------------------------------ geometry

    def transformed_vertices(self, obj: dict[str, Any]) -> list[list[float]]:
        mesh = self.mesh_for(obj["type"])
        scale = obj["scale"]
        position = obj["position"]
        placed: list[list[float]] = []
        for vertex in mesh["vertices"]:
            scaled = [vertex[i] * scale[i] for i in range(3)]
            rotated = _rotate(scaled, obj["rotation"])
            placed.append([round(rotated[i] + position[i], 6) for i in range(3)])
        return placed

    def bounding_box(self) -> dict[str, Any]:
        points = [vertex for obj in self.objects.values() for vertex in self.transformed_vertices(obj)]
        if not points:
            return {"empty": True, "min": None, "max": None, "size": None}
        minimum = [min(point[axis] for point in points) for axis in range(3)]
        maximum = [max(point[axis] for point in points) for axis in range(3)]
        return {
            "empty": False,
            "min": minimum,
            "max": maximum,
            "size": [round(maximum[axis] - minimum[axis], 4) for axis in range(3)],
        }

    # ------------------------------------------------------------------ export

    def export_obj(self, folder_path: str = "3d", name: str = "scene") -> dict[str, Any]:
        """Write a Wavefront OBJ the user can actually open in a viewer."""

        if not self.objects:
            return {"written": False, "reason": "the scene is empty, so there is nothing to export"}

        directory = self._resolve_directory(folder_path)
        os.makedirs(directory, exist_ok=True)
        target = directory / f"{_safe_stem(name)}.obj"

        lines = [f"# H.O.L.M.E.V scene export - {len(self.objects)} object(s)", "o holmev_scene"]
        offset = 0
        for obj in self.objects.values():
            vertices = self.transformed_vertices(obj)
            for vertex in vertices:
                lines.append(f"v {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}")
            for face in self.mesh_for(obj["type"])["faces"]:
                lines.append("f " + " ".join(str(index + offset + 1) for index in face))
            offset += len(vertices)

        content = "\n".join(lines) + "\n"
        target.write_text(content, encoding="utf-8", newline="\n")
        return {
            "written": True,
            "format": "obj",
            "path": str(target),
            "bytes": len(content.encode("utf-8")),
            "objects": len(self.objects),
        }

    def export_stl(self, folder_path: str = "3d", name: str = "scene") -> dict[str, Any]:
        """Write a binary STL: every face triangulated, real normals computed."""

        if not self.objects:
            return {"written": False, "reason": "the scene is empty, so there is nothing to export"}

        directory = self._resolve_directory(folder_path)
        os.makedirs(directory, exist_ok=True)
        target = directory / f"{_safe_stem(name)}.stl"

        triangles: list[tuple[list[float], list[list[float]]]] = []
        for obj in self.objects.values():
            vertices = self.transformed_vertices(obj)
            for face in self.mesh_for(obj["type"])["faces"]:
                corners = [vertices[index - 1] for index in face]
                for triangle in (corners[0:3], [corners[0], corners[2], corners[3]]):
                    triangles.append((_normal(triangle), triangle))

        payload = bytearray()
        payload += b"H.O.L.M.E.V scene".ljust(80, b"\x00")
        payload += struct.pack("<I", len(triangles))
        for normal, triangle in triangles:
            for vector in (normal, *triangle):
                payload += struct.pack("<3f", *vector)
            payload += struct.pack("<H", 0)
        target.write_bytes(bytes(payload))

        return {
            "written": True,
            "format": "stl",
            "path": str(target),
            "bytes": len(payload),
            "triangles": len(triangles),
        }

    @staticmethod
    def _resolve_directory(folder_path: str) -> Path:
        try:
            return guard(folder_path or "3d", root=workspace_root()).resolved
        except PathRejected as exc:
            raise ValueError(f"the export folder was refused by the workspace guard: {exc.reason}") from exc

    def hologram_payload(self, path_points: list[list[float]] | None = None) -> dict[str, Any]:
        """What would be streamed to a projector: the scene plus a route polyline."""

        return {
            "scene": self.get_scene(),
            "summary": self.scene_summary(),
            "path": path_points or [],
            "hardware_note": "geometry only; no projector was detected or addressed",
        }


def _safe_stem(name: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "_" for character in str(name))
    return cleaned.strip("_")[:60] or "scene"


def _normal(triangle: list[list[float]]) -> list[float]:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    u = [bx - ax, by - ay, bz - az]
    v = [cx - ax, cy - ay, cz - az]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    length = math.sqrt(sum(component * component for component in n)) or 1.0
    return [component / length for component in n]


threed_manager = ThreeDManager()
