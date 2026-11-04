"""Tests for the verification engine: a tool's own claim is never proof."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engines.types import PlanStep, ToolOutcome
from app.engines.verification import verification_engine


@pytest.fixture
def workspace(isolated_workspace: Path) -> Path:
    return isolated_workspace


def step(**overrides) -> PlanStep:
    base = {
        "description": "do the thing",
        "tool": "fs.create",
        "params": {"path": "report.txt"},
        "verification": {"type": "path_exists"},
    }
    base.update(overrides)
    return PlanStep(**base)


def outcome(**overrides) -> ToolOutcome:
    base = {"success": True, "data": {"path": "report.txt"}, "metadata": {"tool_claimed": True}}
    base.update(overrides)
    return ToolOutcome(**base)


# ------------------------------------------------------------------ self-report vs proof

def test_a_tool_claiming_success_alone_is_not_independently_verified():
    result = verification_engine.verify(step(verification={"type": "tool_success"}), outcome())
    assert result.verified is True
    assert result.independent is False
    assert "NOT independently verified" in result.reason


def test_a_lying_tool_that_says_it_created_a_file_is_rejected(workspace: Path):
    """The exact failure the old planner had: verified=True with nothing on disk."""

    result = verification_engine.verify(step(), outcome())
    assert result.verified is False
    assert result.failed_checks, "the path check must have failed"
    assert "exists=False" in result.reason
    assert not (workspace / "report.txt").exists()


def test_a_file_that_really_exists_verifies(workspace: Path):
    (workspace / "report.txt").write_text("hello", encoding="utf-8")
    result = verification_engine.verify(step(), outcome())
    assert result.verified is True and result.independent is True
    assert "exists=True" in result.reason


def test_delete_is_verified_by_the_path_being_gone(workspace: Path):
    gone = step(tool="fs.delete", verification={"type": "path_absent"})
    result = verification_engine.verify(gone, outcome())
    assert result.verified is True
    assert result.checks[-1]["kind"] == "path_absent"


def test_delete_that_left_the_file_is_caught(workspace: Path):
    (workspace / "report.txt").write_text("still here", encoding="utf-8")
    gone = step(tool="fs.delete", verification={"type": "path_absent"})
    result = verification_engine.verify(gone, outcome())
    assert result.verified is False
    assert "must be gone" in result.reason


def test_tool_reported_path_wins_over_the_requested_path(workspace: Path):
    """The tool may write somewhere else; verification checks what it says it touched."""

    (workspace / "actual.txt").write_text("x", encoding="utf-8")
    result = verification_engine.verify(
        step(params={"path": "requested.txt"}),
        outcome(data={"path": str(workspace / "actual.txt")}),
    )
    assert result.verified is True
    assert result.checks[-1]["evidence"].endswith("actual.txt")


def test_missing_path_report_cannot_be_verified():
    result = verification_engine.verify(
        step(params={}), outcome(data={"note": "done, no path mentioned"})
    )
    assert result.verified is False
    assert "reported a path" in result.reason


# ------------------------------------------------------------------ the guard holds here too

@pytest.mark.parametrize(
    "escape",
    ["../../Windows/system32/config/SAM", r"C:\\Windows\\win.ini", "\\\\server\\share\\file.txt"],
)
def test_paths_outside_the_workspace_are_refused_not_assumed(escape):
    result = verification_engine.verify(step(params={"path": escape}), outcome(data={"path": escape}))
    assert result.verified is False
    assert "outside the workspace" in result.reason


def test_protected_files_inside_the_workspace_are_refused(workspace: Path):
    (workspace / ".env").write_text("SECRET=1", encoding="utf-8")
    result = verification_engine.verify(
        step(tool="fs.delete", params={"path": ".env"}, verification={"type": "path_absent"}),
        outcome(data={"path": ".env"}),
    )
    assert result.verified is False
    assert "protected-paths" in result.reason


# ------------------------------------------------------------------ content checks

def test_empty_search_results_are_not_a_success(workspace: Path):
    read = step(tool="fs.read", params={"path": "notes.txt"}, verification={"type": "non_empty"})
    (workspace / "notes.txt").write_text("", encoding="utf-8")
    empty = verification_engine.verify(read, outcome(data={"path": "notes.txt", "text": ""}))
    assert empty.verified is False
    assert "0 character" in empty.reason

    filled = verification_engine.verify(read, outcome(data={"text": "found it"}))
    assert filled.verified is True


def test_count_at_least_counts_the_real_list():
    check = step(tool="web.search", params={}, verification={"type": "count_at_least", "count": 3})
    two = verification_engine.verify(check, outcome(data={"snippets": ["a", "b"]}))
    assert two.verified is False
    assert "wanted at least 3" in two.reason

    three = verification_engine.verify(check, outcome(data={"snippets": ["a", "b", "c"]}))
    assert three.verified is True


def test_contains_looks_in_the_tool_output_not_the_request():
    check = step(verification={"type": "contains", "text": "order 4471"})
    assert verification_engine.verify(check, outcome(data={"body": "no such order"})).verified is False
    assert verification_engine.verify(check, outcome(data={"body": "Order 4471 shipped"})).verified is True


def test_state_matches_reads_the_nested_state_the_tool_actually_set():
    check = step(tool="home.device.set_power", params={}, verification={"type": "state_matches",
                                                                       "expect": {"power": False}})
    off = verification_engine.verify(check, outcome(data={"state": {"power": False}, "device": "Hall Fan"}))
    assert off.verified is True

    still_on = verification_engine.verify(check, outcome(data={"state": {"power": True}}))
    assert still_on.verified is False
    assert "wanted False got True" in still_on.reason


def test_state_match_needs_a_declared_expectation():
    check = step(verification={"type": "state_matches"})
    result = verification_engine.verify(check, outcome(data={"state": {"power": True}}))
    assert result.verified is False
    assert "no expected state" in result.reason


def test_json_shape_checks_the_keys_the_next_step_needs():
    check = step(verification={"type": "json_shape", "required_keys": ["pid", "application"]})
    missing = verification_engine.verify(check, outcome(data={"application": "chrome"}))
    assert missing.verified is False
    assert "missing keys: pid" in missing.reason

    complete = verification_engine.verify(check, outcome(data={"application": "chrome", "pid": 4312}))
    assert complete.verified is True


# ------------------------------------------------------------------ failure reporting

def test_an_error_string_overrides_a_success_flag():
    result = verification_engine.verify(step(), outcome(error="device busy"))
    assert result.verified is False
    assert result.independent is False
    assert result.checks[0]["kind"] == "tool_self_report"
    assert "device busy" in result.reason


def test_an_unknown_check_type_is_reported_instead_of_assumed_true():
    result = verification_engine.verify(step(verification={"type": "always_pass"}), outcome())
    assert result.verified is False
    assert "not implemented" in result.reason


def test_a_step_that_never_ran_is_not_verified():
    ran = step(id="s1", description="one", verification={"type": "tool_success"})
    skipped = step(id="s2", description="two", verification={"type": "path_exists"})
    results = verification_engine.verify_chain([ran, skipped], {"s1": outcome()})
    assert results["s1"].verified is True
    assert results["s2"].verified is False
    assert "never executed" in results["s2"].reason
    assert verification_engine.least_verified(results) is results["s2"]


def test_least_verified_finds_the_unproven_step(workspace: Path):
    (workspace / "report.txt").write_text("ok", encoding="utf-8")
    good = step(id="s1", verification={"type": "tool_success"})
    bad = step(id="s2", verification={"type": "path_exists"})
    results = verification_engine.verify_chain([good, bad], {"s1": outcome(), "s2": outcome()})
    weak = verification_engine.least_verified(results)
    assert weak is not None
    assert weak.independent is False or not weak.verified
