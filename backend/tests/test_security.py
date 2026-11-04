"""Adversarial tests for the enforcement layer the old planner skipped."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.security.approvals import ApprovalRejected, approval_service, canonical_param_hash
from app.security.audit import REDACTED, audit_log, redact
from app.security.path_guard import PathRejected, guard, sanitize_filename
from app.security.stop import StopEngaged, emergency_stop


async def make_approval(**kwargs):
    defaults = {
        "tool": "mobile.whatsapp.send",
        "params": {"contact": "Ali", "message": "hello"},
        "permission_level": 2,
        "summary": "Send a WhatsApp message to Ali",
    }
    defaults.update(kwargs)
    return await approval_service.create(**defaults)


@pytest.mark.asyncio
async def test_consequential_tool_cannot_run_without_a_decision():
    record = await make_approval()
    with pytest.raises(ApprovalRejected, match="never granted"):
        await approval_service.consume(record.id, tool=record.tool, params=record.params)


@pytest.mark.asyncio
async def test_approval_is_single_use():
    record = await make_approval()
    await approval_service.decide(record.id, approved=True)
    await approval_service.consume(record.id, tool=record.tool, params=record.params)
    with pytest.raises(ApprovalRejected, match="already used"):
        await approval_service.consume(record.id, tool=record.tool, params=record.params)


@pytest.mark.asyncio
async def test_different_parameters_than_approved_are_blocked():
    record = await make_approval()
    await approval_service.decide(record.id, approved=True)
    with pytest.raises(ApprovalRejected, match="differ from the ones the user approved"):
        await approval_service.consume(
            record.id, tool=record.tool, params={"contact": "Ali", "message": "transfer 50000 rupees"}
        )


@pytest.mark.asyncio
async def test_denied_approval_can_never_be_replayed_as_granted():
    record = await make_approval()
    await approval_service.decide(record.id, approved=False)
    with pytest.raises(ApprovalRejected, match="denied"):
        await approval_service.consume(record.id, tool=record.tool, params=record.params)


@pytest.mark.asyncio
async def test_expired_approval_is_rejected(monkeypatch):
    record = await make_approval(expires_in_s=-1)
    with pytest.raises(ApprovalRejected, match="expired"):
        await approval_service.decide(record.id, approved=True)


@pytest.mark.asyncio
async def test_param_hash_is_stable_regardless_of_key_order():
    a = canonical_param_hash("fs.create", {"b": 2, "a": 1})
    b = canonical_param_hash("fs.create", {"a": 1, "b": 2})
    assert a == b
    assert a != canonical_param_hash("fs.create", {"a": 1, "b": 3})


@pytest.mark.asyncio
async def test_pending_approvals_are_visible_and_voidable_by_stop():
    first = await make_approval(run_id="run_1")
    await make_approval(tool="mobile.phone.call", params={"contact": "Ali"}, run_id="run_2",
                        summary="Call Ali")
    pending = await approval_service.list_pending()
    assert {p.id for p in pending} >= {first.id}

    await emergency_stop.engage("test")
    assert await approval_service.list_pending() == []
    await emergency_stop.resume()


# ---------------------------------------------------------------- path guard

def test_path_inside_workspace_is_allowed(isolated_workspace: Path):
    (isolated_workspace / "notes").mkdir()
    result = guard("notes/todo.txt", root=isolated_workspace)
    assert result.relative == "notes/todo.txt"
    assert result.resolved.is_relative_to(isolated_workspace.resolve())


@pytest.mark.parametrize(
    "attacker_path",
    [
        "../../Windows/SYSTEM32/config/sam",
        "..\\..\\..\\secrets.txt",
        "notes/../../../etc/passwd",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "\\\\attacker\\share\\payload",
        "/etc/passwd",
    ],
)
def test_traversal_and_absolute_escapes_are_rejected(isolated_workspace: Path, attacker_path: str):
    with pytest.raises(PathRejected):
        guard(attacker_path, root=isolated_workspace)


@pytest.mark.parametrize("protected", [".env", ".git/config", "secrets/id_rsa", "sub/.env"])
def test_protected_paths_are_rejected(isolated_workspace: Path, protected: str):
    (isolated_workspace / "sub").mkdir(exist_ok=True)
    with pytest.raises(PathRejected, match="protected-paths list"):
        guard(protected, root=isolated_workspace)


@pytest.mark.parametrize("device_name", ["nul", "CON", "com1.txt", "LPT9"])
def test_windows_reserved_names_are_rejected(isolated_workspace: Path, device_name: str):
    with pytest.raises(PathRejected):
        guard(device_name, root=isolated_workspace)


def test_control_characters_are_rejected(isolated_workspace: Path):
    with pytest.raises(PathRejected):
        guard("evil\x00name", root=isolated_workspace)


def test_empty_path_is_rejected(isolated_workspace: Path):
    for bad in ("", "   ", None):
        with pytest.raises(PathRejected):
            guard(bad, root=isolated_workspace)  # type: ignore[arg-type]


def test_dots_and_spaces_cannot_escape(isolated_workspace: Path):
    result = guard("./notes/./todo.txt", root=isolated_workspace)
    assert result.relative == "notes/todo.txt"
    assert sanitize_filename("a/../b") == "a_.._b"


@pytest.mark.skipif(os.name != "nt", reason="junction test is Windows-specific")
def test_junction_escape_is_rejected(isolated_workspace: Path):
    import subprocess

    outside = isolated_workspace.parent / "outside_secret"
    outside.mkdir(exist_ok=True)
    (outside / "keys.txt").write_text("secret", encoding="utf-8")
    link = isolated_workspace / "link"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True, text=True,
    )
    if created.returncode != 0:
        pytest.skip("could not create a junction in this environment")
    try:
        with pytest.raises(PathRejected):
            guard("link/keys.txt", root=isolated_workspace)
    finally:
        os.rmdir(link)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink test")
def test_symlink_escape_is_rejected(isolated_workspace: Path):
    outside = isolated_workspace.parent / "outside_secret"
    outside.mkdir(exist_ok=True)
    (outside / "keys.txt").write_text("secret", encoding="utf-8")
    link = isolated_workspace / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, PermissionError):
        pytest.skip("symlinks not permitted in this environment")
    with pytest.raises(PathRejected):
        guard("link/keys.txt", root=isolated_workspace)


# ---------------------------------------------------------------- audit

def test_redact_strips_secrets_from_keys_and_values():
    payload = {
        "contact": "Ali",
        "api_key": "sk-live-ABCDEFGHIJKLMNOP",
        "headers": {"Authorization": "Bearer sk-topsecretvalue"},
        "note": "my token is sk-1234567890abcdef",
    }
    cleaned = redact(payload)
    assert cleaned["contact"] == "Ali"
    assert cleaned["api_key"] == REDACTED
    assert cleaned["headers"]["Authorization"] == REDACTED
    assert cleaned["note"] == REDACTED
    assert "ABCDEFGHIJKLMNOP" not in str(cleaned)


@pytest.mark.asyncio
async def test_audit_records_outcomes_and_can_be_queried():
    await audit_log.record(action="tool.execute", tool="fs.create", params={"path": "a.txt"}, outcome="executed",
                           run_id="run_a", permission_level=2)
    await audit_log.record(action="approval.decide", tool="fs.delete", outcome="denied", run_id="run_b")

    run_rows = await audit_log.query(run_id="run_a")
    assert len(run_rows) == 1
    assert run_rows[0].sanitized_params == {"path": "a.txt"}

    denied = await audit_log.query(outcome="denied")
    assert denied[0].tool == "fs.delete"


@pytest.mark.asyncio
async def test_audit_export_contains_no_secrets():
    await audit_log.record(
        action="tool.request", tool="mobile.email.send",
        params={"to": "x@y.z", "password": "hunter2", "token": "sk-abcdefghijklmnop"},
    )
    export = await audit_log.export("json")
    assert "hunter2" not in export
    assert "sk-abcdefghijklmnop" not in export
    assert REDACTED in export


# ---------------------------------------------------------------- stop

@pytest.mark.asyncio
async def test_emergency_stop_blocks_execution_then_resumes():
    from app.providers.base import RunControl

    control = RunControl()
    emergency_stop.register_control("run_live", control)

    await emergency_stop.engage("user pressed STOP")
    with pytest.raises(StopEngaged):
        emergency_stop.guard()
    assert control.cancelled is True

    status = emergency_stop.status()
    assert status["engaged"] is True
    assert status["reason"] == "user pressed STOP"

    await emergency_stop.resume()
    emergency_stop.guard()
    assert emergency_stop.status()["engaged"] is False
