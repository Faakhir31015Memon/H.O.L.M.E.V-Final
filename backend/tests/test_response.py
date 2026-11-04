"""Tests for the response engine: the model words it, the digest decides what is true."""

from __future__ import annotations

import pytest

from app.engines.response import response_engine
from app.engines.types import (
    Plan,
    PlanStep,
    TaskUnderstanding,
    ToolOutcome,
    VerificationResult,
)
from app.providers.base import ModelInfo
from app.providers.mock import MockAdapter
from app.providers.registry import ModelRegistry


@pytest.fixture
async def model_env(monkeypatch):
    reg = ModelRegistry()
    adapter = MockAdapter(
        models=[
            ModelInfo(
                provider="ollama",
                name="qwen2.5:3b",
                capabilities={"chat", "reasoning", "tool_use", "structured_output"},
            )
        ]
    )
    adapter.provider = "ollama"
    reg.register(adapter)
    await reg.refresh()
    monkeypatch.setattr("app.providers.router.registry", reg)
    return adapter


def understanding(**kw) -> TaskUnderstanding:
    base = {"task_type": "file_task", "complexity": "moderate", "risk_level": "low"}
    base.update(kw)
    return TaskUnderstanding(**base)


def make_step(step_id: str = "s1", description: str = "create the report") -> PlanStep:
    return PlanStep(id=step_id, description=description, tool="fs.create", params={"path": "report.txt"})


VERIFIED = VerificationResult(
    verified=True, independent=True, reason="report.txt exists=True, must exist",
    checks=[{"kind": "path_exists", "passed": True}],
)
UNPROVEN = VerificationResult(
    verified=True, independent=False, reason="tool reported success only",
    checks=[{"kind": "tool_self_report", "passed": True}],
)
FAILED = VerificationResult(
    verified=False, independent=True, reason="report.txt exists=False, must exist",
    checks=[{"kind": "path_exists", "passed": False}],
)


def prompt_of(adapter: MockAdapter, index: int = 0) -> str:
    return adapter.requests[index].messages[0].content


# ------------------------------------------------------------------ fact digest

def test_unverified_step_is_labelled_unproven_in_the_digest():
    lines = response_engine.build_digest(
        Plan(goal="g", steps=[make_step()]), {"s1": ToolOutcome(success=True)}, {"s1": UNPROVEN}
    )
    assert lines[0].status == "done, unproven"
    assert lines[0].verified is False
    assert "NOT independently verified" in lines[0].as_line()


def test_a_step_that_was_never_run_is_not_reported_as_done():
    lines = response_engine.build_digest(Plan(goal="g", steps=[make_step()]), {}, {})
    assert lines[0].status == "not executed"
    assert lines[0].detail == "no result was produced"


def test_a_step_that_failed_its_check_is_not_called_a_completion():
    """The tool said success, the world disagreed - the digest must side with the world."""

    lines = response_engine.build_digest(
        Plan(goal="g", steps=[make_step()]), {"s1": ToolOutcome(success=True)}, {"s1": FAILED}
    )
    assert lines[0].status == "check failed"
    assert response_engine._status_header(lines) == "Nothing was completed."


def test_header_reflects_the_real_outcome_not_the_hope():
    one = Plan(goal="g", steps=[make_step("s1"), make_step("s2", "call the boss")])
    outcomes = {"s1": ToolOutcome(success=True), "s2": ToolOutcome(success=False, error="line busy")}
    verifs = {"s1": VERIFIED, "s2": FAILED}
    lines = response_engine.build_digest(one, outcomes, verifs)
    assert response_engine._status_header(lines) == "Partly completed."

    all_bad = response_engine.build_digest(
        one, {"s1": ToolOutcome(success=False)}, {"s1": FAILED, "s2": FAILED}
    )
    assert response_engine._status_header(all_bad) == "Nothing was completed."


def test_digest_quotes_the_data_the_tool_returned():
    lines = response_engine.build_digest(
        Plan(goal="g", steps=[make_step()]),
        {"s1": ToolOutcome(success=True, data={"path": "report.txt", "snippets": ["a", "b"]})},
        {"s1": VERIFIED},
    )
    assert "path=report.txt" in lines[0].detail
    assert "snippets=2 item(s)" in lines[0].detail


# ------------------------------------------------------------------ model composed the answer

@pytest.mark.asyncio
async def test_the_model_writes_the_reply_not_a_lookup_table(model_env):
    model_env.queue("Report ban gaya, Boss.")
    draft = await response_engine.compose(
        goal="report bana do",
        understanding=understanding(language="roman_urdu"),
        plan=Plan(goal="g", steps=[make_step()]),
        outcomes={"s1": ToolOutcome(success=True, data={"path": "report.txt"})},
        verifications={"s1": VERIFIED},
    )
    assert model_env.call_count == 1
    assert draft.text == "Report ban gaya, Boss."
    assert draft.degraded is False


@pytest.mark.asyncio
async def test_the_prompt_carries_the_verified_language_and_no_invention(model_env):
    model_env.queue("ok")
    await response_engine.compose(
        goal="delete the old logs",
        understanding=understanding(task_type="home_control", language="roman_urdu"),
        plan=Plan(goal="g", steps=[make_step()]),
        outcomes={"s1": ToolOutcome(success=True)},
        verifications={"s1": UNPROVEN},
    )
    prompt = prompt_of(model_env)
    assert "Roman Urdu" in prompt
    assert "NOT independently verified" in prompt
    assert "only things you may claim happened" in prompt
    assert "1 short sentence" in prompt or "short sentence" in prompt


@pytest.mark.asyncio
async def test_mood_is_a_hint_never_a_claim(model_env):
    model_env.queue("theek hain Boss")
    await response_engine.compose(
        goal="hello",
        understanding=understanding(task_type="chat", language="roman_urdu"),
        plan=Plan(goal="g", steps=[]),
        outcomes={},
        verifications={},
        emotion="STRESSED",
    )
    prompt = prompt_of(model_env)
    assert "heuristic" in prompt
    assert "never state it as a fact" in prompt or "possibly wrong" in prompt

    model_env.queue("hello")
    await response_engine.compose(
        goal="hello",
        understanding=understanding(task_type="chat", language="english"),
        plan=Plan(goal="g", steps=[]),
        outcomes={},
        verifications={},
        emotion="NEUTRAL",
    )
    assert "mood" not in prompt_of(model_env, 1).lower()


@pytest.mark.asyncio
async def test_a_plain_question_does_not_get_a_tool_digest(model_env):
    model_env.queue("Paani din mein 8 glas piyein.")
    draft = await response_engine.compose(
        goal="kitna paani peena chahiye",
        understanding=understanding(task_type="chat", complexity="simple", language="roman_urdu"),
        plan=Plan(goal="g", steps=[]),
        outcomes={},
        verifications={},
    )
    prompt = prompt_of(model_env)
    assert "Facts:" not in prompt
    assert "Answer this directly" in prompt
    assert draft.text == "Paani din mein 8 glas piyein."


# ------------------------------------------------------------------ degraded honesty

@pytest.mark.asyncio
async def test_without_a_model_the_facts_are_still_told_honestly(monkeypatch):
    reg = ModelRegistry()
    monkeypatch.setattr("app.providers.router.registry", reg)
    draft = await response_engine.compose(
        goal="create the report",
        understanding=understanding(),
        plan=Plan(goal="g", steps=[make_step()]),
        outcomes={"s1": ToolOutcome(success=True, data={"path": "report.txt"})},
        verifications={"s1": UNPROVEN},
    )
    assert draft.degraded is True
    assert "Done, but not independently verified." in draft.text
    assert "create the report: done, unproven" in draft.text
    assert "NOT independently verified" in draft.text
    assert draft.notes, "the setup hint must reach the user"


@pytest.mark.asyncio
async def test_a_failed_step_is_never_reported_as_success_in_the_fallback(monkeypatch):
    reg = ModelRegistry()
    monkeypatch.setattr("app.providers.router.registry", reg)
    draft = await response_engine.compose(
        goal="create the report",
        understanding=understanding(),
        plan=Plan(goal="g", steps=[make_step()]),
        outcomes={"s1": ToolOutcome(success=False, error="disk full")},
        verifications={"s1": FAILED},
    )
    assert draft.text.startswith("Nothing was completed.")
    assert "failed" in draft.text


@pytest.mark.asyncio
async def test_a_silent_model_falls_back_instead_of_replying_empty(model_env):
    model_env.queue("")
    draft = await response_engine.compose(
        goal="create the report",
        understanding=understanding(),
        plan=Plan(goal="g", steps=[make_step()]),
        outcomes={"s1": ToolOutcome(success=True)},
        verifications={"s1": VERIFIED},
    )
    assert draft.degraded is True
    assert "Completed." in draft.text
    assert "no usable answer" in draft.notes[0]
