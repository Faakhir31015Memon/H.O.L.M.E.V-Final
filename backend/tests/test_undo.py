"""Undo tests: a reversal either provably restores something or it refuses.

Each case captures the pre-image *before* the action, the way the execution engine
does, then reverses it and checks the filesystem or the device registry itself -
never the undo module's own report.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.engines.execution import execution_engine
from app.engines.types import Plan, PlanStep
from app.security.undo import MAX_SNAPSHOT_BYTES, UndoUnavailable, handles_reversible_action, undo_engine


@pytest.fixture
def workspace(isolated_workspace: Path) -> Path:
    return isolated_workspace


def capture(tool: str, params: dict) -> dict:
    return undo_engine.capture_before(tool, params)


async def record(tool: str, params: dict, before: dict) -> str:
    entry = await undo_engine.record(
        run_id="run_undo_test", approval_id=None, tool=tool, params=params, before=before
    )
    return entry.id


@pytest.mark.asyncio
async def test_creating_a_folder_then_undoing_puts_it_in_the_trash(workspace: Path):
    target = workspace / "projects"
    before = capture("desktop.create_folder", {"folder_path": "projects"})
    assert before["kind"] == "created"

    target.mkdir()
    (target / "inside.txt").write_text("work", encoding="utf-8")

    record_id = await record("desktop.create_folder", {"folder_path": "projects"}, before)
    result = await undo_engine.undo(record_id)

    assert not target.exists()
    assert result["action"] == "moved to trash"
    assert (workspace / ".holmev_trash" / result["trash"] / "inside.txt").read_text(encoding="utf-8") == "work"


@pytest.mark.asyncio
async def test_undoing_an_overwrite_restores_the_previous_bytes(workspace: Path):
    note = workspace / "note.txt"
    note.write_text("original", encoding="utf-8")

    before = capture("file.write", {"path": "note.txt"})
    assert before["kind"] == "created" and before["overwrote"] is True

    note.write_text("clobbered", encoding="utf-8")
    record_id = await record("file.write", {"path": "note.txt"}, before)
    await undo_engine.undo(record_id)

    assert note.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_deleting_then_undoing_brings_the_file_back(workspace: Path):
    victim = workspace / "logs" / "keep.txt"
    victim.parent.mkdir()
    victim.write_text("precious", encoding="utf-8")

    before = capture("file.delete", {"path": "logs/keep.txt"})
    assert before["kind"] == "deleted"

    victim.unlink()
    record_id = await record("file.delete", {"path": "logs/keep.txt"}, before)
    await undo_engine.undo(record_id)

    assert victim.read_text(encoding="utf-8") == "precious"


@pytest.mark.asyncio
async def test_a_restore_never_overwrites_newer_work(workspace: Path):
    victim = workspace / "data.csv"
    victim.write_text("old", encoding="utf-8")

    before = capture("file.delete", {"path": "data.csv"})
    victim.unlink()
    victim.write_text("written by someone else meanwhile", encoding="utf-8")

    record_id = await record("file.delete", {"path": "data.csv"}, before)
    with pytest.raises(UndoUnavailable, match="exists again already"):
        await undo_engine.undo(record_id)
    assert victim.read_text(encoding="utf-8") == "written by someone else meanwhile"


@pytest.mark.asyncio
async def test_a_missing_trash_copy_is_reported_instead_of_claimed(workspace: Path):
    victim = workspace / "gone.txt"
    victim.write_text("x", encoding="utf-8")

    before = capture("file.delete", {"path": "gone.txt"})
    record_id = await record("file.delete", {"path": "gone.txt"}, before)
    victim.unlink()
    (workspace / ".holmev_trash" / before["copy"]).unlink()

    with pytest.raises(UndoUnavailable, match="staged copy"):
        await undo_engine.undo(record_id)


@pytest.mark.asyncio
async def test_an_action_outside_the_workspace_is_never_promised_as_reversible():
    before = capture("file.delete", {"path": "../../Windows/System32/config"})
    assert before["kind"] == "none"
    assert "guard" in before["reason"]


@pytest.mark.asyncio
async def test_a_file_too_large_to_snapshot_is_declared_irreversible(workspace: Path):
    big = workspace / "big.bin"
    big.write_bytes(b"0" * (MAX_SNAPSHOT_BYTES + 1))

    before = capture("file.delete", {"path": "big.bin"})
    assert before["kind"] == "none"
    assert "larger than" in before["reason"]

    record_id = await record("file.delete", {"path": "big.bin"}, before)
    with pytest.raises(UndoUnavailable):
        await undo_engine.undo(record_id)
    assert big.exists()


@pytest.mark.asyncio
async def test_a_move_is_reported_as_irreversible_rather_than_guessed():
    before = capture("file.move", {"path": "a.txt", "destination": "b.txt"})
    assert before["kind"] == "none"
    assert "move" in before["reason"]


@pytest.mark.asyncio
async def test_a_message_with_no_path_and_no_device_cannot_be_undone():
    before = capture("mobile.whatsapp.send", {"contact": "Ali", "message": "hi"})
    assert before == {"kind": "none", "reason": "this action names no file and no device"}

    record_id = await record("mobile.whatsapp.send", {"contact": "Ali"}, before)
    with pytest.raises(UndoUnavailable, match="names no file"):
        await undo_engine.undo(record_id)


@pytest.mark.asyncio
async def test_a_device_command_is_undoable_only_for_a_registered_device():
    before = capture("home.device.set_power", {"room": "Bedroom", "device_type": "fan", "power": False})
    assert before["kind"] == "device"
    assert before["previous_state"]["power"] is True

    unknown = capture("home.device.set_power", {"room": "Attic", "device_type": "elevator"})
    assert unknown["kind"] == "none"
    assert "no registered device" in unknown["reason"]


@pytest.mark.asyncio
async def test_switching_a_device_off_then_undoing_switches_it_back():
    from app.devices.registry import device_registry

    light = device_registry.devices["dev_hall_light"]
    state_before = dict(light["state"])
    params = {"room": "Hall", "device_type": "light", "power": False}

    before = capture("home.device.set_power", params)
    assert before["kind"] == "device"

    record_id = await record("home.device.set_power", params, before)
    await device_registry.execute_device_command(device_id="dev_hall_light", power=False)
    assert light["state"]["power"] is False

    await undo_engine.undo(record_id)
    assert light["state"] == state_before


@pytest.mark.parametrize(
    ("tool", "reversible"),
    [
        ("desktop.create_folder", True),
        ("file.delete", True),
        ("home.device.set_power", True),
        ("web.search", False),
        ("memory.store", False),
        ("home.cctv.show", False),
    ],
)
def test_only_consequential_tools_get_a_pre_image(tool: str, reversible: bool):
    assert handles_reversible_action(tool) is reversible


@pytest.mark.asyncio
async def test_a_succeeded_step_leaves_an_undo_record_behind(workspace: Path):
    plan = Plan(
        goal="make a folder",
        steps=[
            PlanStep(
                id="s1",
                description="Create reports folder",
                tool="desktop.create_folder",
                params={"folder_path": "reports"},
                required_permission=1,
            )
        ],
    )

    report = await execution_engine.run_plan(plan, run_id="run_exec_undo", session_id="s")
    assert report.executions[0].status == "succeeded"
    assert (workspace / "reports").is_dir()

    records = await undo_engine.list_records(run_id="run_exec_undo")
    assert len(records) == 1
    assert records[0].status == "available"
    assert records[0].detail["kind"] == "created"

    await undo_engine.undo(records[0].id)
    assert not (workspace / "reports").exists()


@pytest.mark.asyncio
async def test_a_failed_step_records_nothing(workspace: Path):
    plan = Plan(
        goal="escape the workspace",
        steps=[
            PlanStep(
                id="s1",
                description="Create outside the root",
                tool="desktop.create_folder",
                params={"folder_path": "../../outside"},
                required_permission=1,
            )
        ],
    )

    await execution_engine.run_plan(plan, run_id="run_exec_blocked", session_id="s")
    assert await undo_engine.list_records(run_id="run_exec_blocked") == []
    assert not (workspace.parent / "outside").exists()


@pytest.mark.asyncio
async def test_a_record_can_only_be_reversed_once(workspace: Path):
    before = capture("file.write", {"path": "once.txt"})
    (workspace / "once.txt").write_text("v2", encoding="utf-8")
    record_id = await record("file.write", {"path": "once.txt"}, before)

    await undo_engine.undo(record_id)
    with pytest.raises(UndoUnavailable, match="undone"):
        await undo_engine.undo(record_id)


def test_the_trash_lives_inside_the_workspace(workspace: Path):
    assert undo_engine.trash_root() == workspace / ".holmev_trash"
    assert str(workspace) in os.fspath(undo_engine.trash_root())
