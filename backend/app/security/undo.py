"""Undo: reverse what the brain did, or say plainly that it cannot.

Reversibility is only real when the before-state was captured before the action,
so `capture_before()` runs first and the record holds what it found. Three kinds
of reversal are actually implemented:

* **created** - the path did not exist before, so it goes to a trash folder inside
  the workspace (not deleted, because an undo of an undo should also work);
* **deleted** - a copy was kept when the file was small enough, so it is put back;
* **device** - the registry's state before the command is commanded again.

Anything else is recorded as `none` and refuses to pretend: an assistant that says
"undone" about something it cannot reverse is worse than one that says "irreversible".
Every path is put through the same guard the forward direction used.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database.models import UndoRecord
from app.database.session import session_scope
from app.security.audit import audit_log
from app.security.path_guard import PathRejected, guard, workspace_root

logger = logging.getLogger("holmev.undo")

TRASH_DIRNAME = ".holmev_trash"
MAX_SNAPSHOT_BYTES = 2_000_000
DEVICE_TOOLS = ("home.device.set_power",)
PATH_WORDS = ("create", "delete", "remove", "folder", "write", "move")


def handles_reversible_action(tool: str) -> bool:
    """One rule for 'is this worth capturing a pre-image for', used by the engine and here."""

    lowered = (tool or "").lower()
    return any(word in lowered for word in DEVICE_TOOLS) or any(word in lowered for word in PATH_WORDS)


class UndoUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _path_param(params: dict[str, Any]) -> str:
    for key in ("path", "file_path", "folder_path", "directory", "target_path", "save_path"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _relative(path: Path) -> str:
    try:
        return path.relative_to(workspace_root().resolve()).as_posix()
    except ValueError:
        return str(path)


class UndoEngine:
    def trash_root(self) -> Path:
        return workspace_root() / TRASH_DIRNAME

    # ------------------------------------------------------------------ capture

    def capture_before(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        """Record the pre-image. Runs before the tool, so it sees the world as it was."""

        lowered = (tool or "").lower()

        if any(word in lowered for word in DEVICE_TOOLS):
            return self._capture_device(params)

        raw = _path_param(params)
        if not raw:
            return {"kind": "none", "reason": "this action names no file and no device"}

        try:
            guarded = guard(raw, root=workspace_root())
        except PathRejected as exc:
            return {"kind": "none", "reason": f"path was refused by the guard: {exc.reason}"}

        target = guarded.resolved

        if "delete" in lowered or "remove" in lowered:
            return self._capture_delete(target)
        if "move" in lowered:
            return {
                "kind": "none",
                "path": _relative(target),
                "reason": "a move was not staged, so it cannot be reversed automatically",
            }
        return self._capture_create(target)

    def _capture_create(self, target: Path) -> dict[str, Any]:
        existed = target.exists()
        detail: dict[str, Any] = {"kind": "created", "path": _relative(target), "existed_before": existed}
        if existed:
            # Overwriting is not creating; keep the old bytes so undo restores them.
            staged = self._stage(target)
            if staged is None:
                return {"kind": "none", "path": _relative(target),
                        "reason": f"'{target.name}' already existed and is too large to snapshot"}
            detail["overwrote"] = True
            detail["previous_copy"] = staged
        return detail

    def _capture_delete(self, target: Path) -> dict[str, Any]:
        if not target.exists():
            return {"kind": "none", "path": _relative(target), "reason": "that path was already absent"}
        staged = self._stage(target)
        if staged is None:
            return {"kind": "none", "path": _relative(target),
                    "reason": f"'{target.name}' is larger than {MAX_SNAPSHOT_BYTES} bytes, so no copy was kept"}
        return {"kind": "deleted", "path": _relative(target), "copy": staged}

    def _capture_device(self, params: dict[str, Any]) -> dict[str, Any]:
        """Same matching rule the registry uses, so undo targets the device that ran."""

        from app.devices.registry import device_registry

        room = str(params.get("room") or "").lower().strip()
        device_type = str(params.get("device_type") or "").lower().strip()
        for device in device_registry.devices.values():
            dev_room = str(device["room"]).lower()
            dev_type = str(device["device_type"]).lower()
            room_matches = dev_room in room or room in dev_room
            type_matches = dev_type in device_type or device_type in dev_type
            if room and device_type and room_matches and type_matches:
                return {
                    "kind": "device",
                    "device_id": device["id"],
                    "name": device["name"],
                    "previous_state": dict(device.get("state") or {}),
                }
        return {"kind": "none", "reason": f"no registered device matched room='{room}' type='{device_type}'"}

    def _stage(self, target: Path) -> str | None:
        """Copy a path into the workspace trash. Returns None when it is too big."""

        try:
            size = target.stat().st_size if target.is_file() else sum(
                f.stat().st_size for f in target.rglob("*") if f.is_file()
            )
        except OSError as exc:
            logger.info("could not measure '%s': %s", target, exc)
            return None
        if size > MAX_SNAPSHOT_BYTES:
            return None

        trash = self.trash_root()
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / f"{uuid.uuid4().hex[:8]}_{target.name}"
        try:
            if target.is_dir():
                shutil.copytree(target, destination)
            else:
                shutil.copy2(target, destination)
        except OSError as exc:
            logger.warning("staging '%s' failed: %s", target, exc)
            return None
        return destination.name

    # ------------------------------------------------------------------ recording

    async def record(
        self, *, run_id: str, approval_id: str | None, tool: str, params: dict[str, Any],
        before: dict[str, Any]
    ) -> UndoRecord:
        record = UndoRecord(
            run_id=run_id,
            approval_id=approval_id,
            tool=tool,
            target=(before.get("path") or str(params.get("device") or _path_param(params) or tool))[:500],
            snapshot_dir=str(workspace_root()),
            detail=before,
            status="available" if before.get("kind") != "none" else "unreversible",
            created_at=datetime.now(timezone.utc),
        )
        async with session_scope() as db:
            db.add(record)
        return record

    async def list_records(
        self, *, run_id: str | None = None, status: str | None = "available", limit: int = 50
    ) -> list[UndoRecord]:
        stmt = select(UndoRecord).order_by(UndoRecord.created_at.desc()).limit(min(limit, 200))
        if run_id:
            stmt = stmt.where(UndoRecord.run_id == run_id)
        if status:
            stmt = stmt.where(UndoRecord.status == status)
        async with session_scope() as db:
            return list((await db.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------ reversal

    async def undo(self, record_id: str) -> dict[str, Any]:
        async with session_scope() as db:
            record = await db.get(UndoRecord, record_id)
            if record is None:
                raise UndoUnavailable(f"No undo record with id '{record_id}'.")
            detail = dict(record.detail or {})
            if record.status != "available":
                reason = str(detail.get("reason") or "").strip()
                raise UndoUnavailable(
                    f"That action is '{record.status}' and cannot be reversed"
                    + (f": {reason}" if reason else ".")
                )
            tool, run_id = record.tool, record.run_id

        kind = detail.get("kind")
        if kind == "none":
            raise UndoUnavailable(str(detail.get("reason") or "no pre-image was captured for this action"))

        if kind == "device":
            result = await self._undo_device(detail)
        elif kind == "created":
            result = await self._undo_create(detail)
        elif kind == "deleted":
            result = await self._undo_delete(detail)
        else:
            raise UndoUnavailable(f"undo does not know how to reverse kind '{kind}'")

        async with session_scope() as db:
            record = await db.get(UndoRecord, record_id)
            if record is not None:
                record.status = "undone"
                record.undone_at = datetime.now(timezone.utc)

        await audit_log.record(
            action="undo.performed",
            outcome="success",
            actor="user",
            run_id=run_id,
            tool=tool,
            params={"undo_id": record_id, **result},
        )
        return {"undo_id": record_id, "reversed": True, **result}

    def _resolve(self, relative_path: str) -> Path:
        guarded = guard(relative_path, root=workspace_root())
        return guarded.resolved

    async def _undo_create(self, detail: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve(str(detail["path"]))
        if detail.get("overwrote"):
            staged = self.trash_root() / str(detail["previous_copy"])
            if not staged.exists():
                raise UndoUnavailable("the backup copy of the overwritten file is gone")
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if staged.is_dir():
                shutil.copytree(staged, target)
            else:
                shutil.copy2(staged, target)
            return {"action": "restored previous contents", "path": str(detail["path"])}

        if not target.exists():
            return {"action": "nothing to remove", "path": str(detail["path"])}
        # Moved to trash rather than deleted: the user may want it back again.
        staged = self._stage(target)
        if staged is None:
            raise UndoUnavailable(
                f"'{target.name}' is now larger than the snapshot limit, so it was left in place"
            )
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"action": "moved to trash", "path": str(detail["path"]), "trash": staged}

    async def _undo_delete(self, detail: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve(str(detail["path"]))
        staged = self.trash_root() / str(detail["copy"])
        if not staged.exists():
            raise UndoUnavailable("the staged copy of the deleted path is gone")
        if target.exists():
            raise UndoUnavailable(
                f"'{target.name}' exists again already, so restoring over it would destroy newer work"
            )
        if staged.is_dir():
            shutil.copytree(staged, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged, target)
        return {"action": "restored from trash", "path": str(detail["path"])}

    async def _undo_device(self, detail: dict[str, Any]) -> dict[str, Any]:
        from app.devices.registry import device_registry

        previous = dict(detail.get("previous_state") or {})
        if "power" not in previous:
            raise UndoUnavailable("the device's previous state did not include a power setting")
        success, _claimed, state, err = await device_registry.execute_device_command(
            device_id=str(detail["device_id"]),
            power=bool(previous.get("power")),
            speed=previous.get("speed"),
        )
        if err or not success:
            raise UndoUnavailable(f"the device refused to go back: {err}")
        return {"action": "device state restored", "device": detail.get("name"), "state": state}


undo_engine = UndoEngine()
