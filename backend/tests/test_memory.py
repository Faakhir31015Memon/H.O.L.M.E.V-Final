"""Tests for the memory engine: consent before storage, explainable retrieval."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.memory import MemoryBlocked, memory_engine, sensitive_reason
from app.security.audit import contains_secret_value


@pytest.fixture(autouse=True)
async def clean_memory(isolated_workspace):
    memory_engine.clear_working()
    await memory_engine.purge_all()
    yield
    memory_engine.clear_working()
    await memory_engine.purge_all()


# ------------------------------------------------------------------ consent gate

@pytest.mark.asyncio
async def test_a_proposal_is_pending_until_the_user_confirms_it():
    result = await memory_engine.propose(key="favourite_room", value="Hall")
    assert result.stored and result.record.state == "pending"

    hits = await memory_engine.retrieve("favourite room", session="s1")
    assert hits == [], "nothing the user has not confirmed may reach the prompt"

    confirmed = await memory_engine.confirm(result.record.id)
    assert confirmed.state == "active"
    hits = await memory_engine.retrieve("favourite room", session="s1")
    assert [h.record.value for h in hits] == ["Hall"]


@pytest.mark.asyncio
async def test_rejection_keeps_the_memory_out_of_retrieval():
    result = await memory_engine.propose(key="nickname", value="Boss")
    await memory_engine.reject(result.record.id)
    assert await memory_engine.retrieve("nickname", session="s1") == []


@pytest.mark.asyncio
async def test_an_unknown_state_is_refused_rather_than_stored_somewhere_odd():
    with pytest.raises(MemoryBlocked):
        await memory_engine.propose(key="a", value="b", state="hidden")


@pytest.mark.asyncio
async def test_confirming_something_that_does_not_exist_returns_none():
    assert await memory_engine.confirm("nope") is None


# ------------------------------------------------------------------ sensitive data gate

@pytest.mark.parametrize(
    ("key", "value", "label"),
    [
        ("wifi_password", "hunter2", "credential"),
        ("openai api key", "paste the key here", "credential"),
        ("bank", "credit card 4111 1111 1111 1111", "payment_data"),
        ("note", "my cnic is 35202-1234567-1", "government_id"),
        ("doctor", "diabetes medication dose is 500", "health"),
        ("belief", "religion: islam", "religion"),
        ("about me", "caste: something", "ethnicity"),
        ("about me", "sexual orientation: gay", "sexuality"),
        ("voting", "political party: whoever", "political"),
        ("device", "fingerprint template stored", "biometric"),
    ],
)
async def test_protected_categories_are_never_written(key, value, label):
    result = await memory_engine.propose(key=key, value=value)
    assert result.stored is False
    assert label in (result.blocked_reason or "")
    assert await memory_engine.list_memories(state=None) == []


@pytest.mark.asyncio
async def test_a_live_secret_is_blocked_even_without_the_word_secret():
    value = "sk-proj-" + "A" * 40
    assert contains_secret_value(value)
    result = await memory_engine.propose(key="helper token", value=value)
    assert result.stored is False
    assert "live credential" in result.blocked_reason


@pytest.mark.asyncio
async def test_harmless_preferences_are_not_collateral_damage():
    for key, value in (("favourite_room", "Hall"), ("spouse", "Sana"), ("alarm_time", "07:00")):
        result = await memory_engine.propose(key=key, value=value)
        assert result.stored is True, result.blocked_reason


def test_the_policy_function_is_usable_on_its_own():
    assert sensitive_reason("password", "letmein") is not None
    assert sensitive_reason("city", "Lahore") is None


@pytest.mark.asyncio
async def test_empty_and_oversized_memories_are_refused():
    with pytest.raises(MemoryBlocked):
        await memory_engine.propose(key="", value="x")
    with pytest.raises(MemoryBlocked):
        await memory_engine.propose(key="wall", value="x" * 5000)


# ------------------------------------------------------------------ retrieval quality

@pytest.mark.asyncio
async def test_ranking_prefers_the_memory_that_actually_matches():
    for key, value in (
        ("favourite_room", "Hall"),
        ("car_model", "Honda Civic"),
        ("coffee_order", "double espresso no sugar"),
    ):
        await memory_engine.propose(key=key, value=value, state="active")

    hits = await memory_engine.retrieve("which room do I like", session="s1", limit=3)
    assert hits[0].record.key == "favourite_room"
    assert "room" in hits[0].terms

    other = await memory_engine.retrieve("espresso", session="s1")
    assert other[0].record.key == "coffee_order"


@pytest.mark.asyncio
async def test_a_word_shared_by_every_memory_is_worth_less():
    for key, value in (("note_one", "common rare_alpha"), ("note_two", "common plain"),
                       ("note_three", "common plain")):
        await memory_engine.propose(key=key, value=value, state="active")

    hits = await memory_engine.retrieve("common rare_alpha", session="s1", limit=5)
    assert hits[0].record.key == "note_one"
    shared = [h for h in hits if "common" in h.terms]
    assert shared, "the common word must still match, just not win"


@pytest.mark.asyncio
async def test_a_stale_memory_ranks_below_a_recent_one():
    fresh = await memory_engine.propose(key="address", value="Office", state="active")
    stale = await memory_engine.propose(key="address", value="Home", state="active")
    assert fresh.record and stale.record

    from app.database.models import BrainMemory
    from app.database.session import session_scope

    async with session_scope() as db:
        row = await db.get(BrainMemory, stale.record.id)
        row.updated_at = datetime.now(timezone.utc) - timedelta(days=120)

    hits = await memory_engine.retrieve("address", session="s1", limit=2)
    assert hits[0].record.value == "Office", "recency must break the tie"
    assert hits[0].recency > hits[1].recency


@pytest.mark.asyncio
async def test_low_confidence_is_penalised_not_ignored():
    sure = await memory_engine.propose(key="route to office", value="Motorway", confidence=0.95, state="active")
    unsure = await memory_engine.propose(key="route to office", value="Gulberg", confidence=0.2, state="active")
    hits = await memory_engine.retrieve("route office", session="s1", limit=2)
    assert hits[0].record.id == sure.record.id
    assert hits[1].record.id == unsure.record.id


# ------------------------------------------------------------------ session isolation

@pytest.mark.asyncio
async def test_working_memory_never_crosses_sessions():
    memory_engine.remember_turn("session_a", "user", "mera naam Ali hai")
    memory_engine.remember_turn("session_b", "user", "mera naam Sana hai")

    hits_a = await memory_engine.retrieve("naam", session="session_a")
    hits_b = await memory_engine.retrieve("naam", session="session_b")
    assert [h.record.value for h in hits_a] == ["mera naam Ali hai"]
    assert [h.record.value for h in hits_b] == ["mera naam Sana hai"]
    assert all(h.source == "working" for h in hits_a)


@pytest.mark.asyncio
async def test_working_layer_writes_nothing_to_disk():
    memory_engine.remember_turn("session_a", "user", "hello")
    assert await memory_engine.list_memories(state=None) == []


@pytest.mark.asyncio
async def test_working_layer_is_bounded():
    for index in range(60):
        memory_engine.remember_turn("session_a", "user", f"turn {index}")
    assert len(memory_engine.working("session_a")) == 40


# ------------------------------------------------------------------ packing + admin

@pytest.mark.asyncio
async def test_context_pack_stays_inside_the_token_budget():
    for index in range(20):
        await memory_engine.propose(
            key=f"preference_{index}", value="word " * 200, state="active"
        )
    included, trace = await memory_engine.context_pack("preference word", session="s1", budget_tokens=300)
    assert included, "at least one memory must fit"
    assert sum(item["tokens_est"] for item in included) <= 300
    assert any(not item.included for item in trace)
    assert all("matched" in item.reason for item in trace if item.included)


@pytest.mark.asyncio
async def test_forget_removes_only_the_named_memory():
    one = await memory_engine.propose(key="room", value="Hall", state="active")
    await memory_engine.propose(key="car", value="Civic", state="active")
    assert await memory_engine.forget(one.record.id) is True
    remaining = await memory_engine.list_memories()
    assert [record.key for record in remaining] == ["car"]


@pytest.mark.asyncio
async def test_forget_matching_uses_the_same_ranking_as_retrieval():
    await memory_engine.propose(key="cctv_camera", value="Hallway cam", state="active")
    await memory_engine.propose(key="cctv_camera_2", value="Drive cam", state="active")
    await memory_engine.propose(key="coffee_order", value="Espresso", state="active")
    removed = await memory_engine.forget_matching("cctv camera", session="s1")
    assert len(removed) == 2
    assert [record.key for record in await memory_engine.list_memories()] == ["coffee_order"]


@pytest.mark.asyncio
async def test_purge_all_leaves_nothing_behind():
    await memory_engine.propose(key="room", value="Hall", state="active")
    memory_engine.remember_turn("s1", "user", "hello")
    assert await memory_engine.purge_all() == 1
    assert await memory_engine.list_memories(state=None) == []
    assert memory_engine.working("s1") == []


@pytest.mark.asyncio
async def test_export_covers_pending_memories_too_so_nothing_is_hidden():
    await memory_engine.propose(key="room", value="Hall")
    await memory_engine.propose(key="car", value="Civic", state="active")

    payload = json.loads(await memory_engine.export("json"))
    assert len(payload) == 2
    assert {item["state"] for item in payload} == {"pending", "active"}

    csv_text = await memory_engine.export("csv")
    assert csv_text.splitlines()[0].startswith("id,layer,key,value,state")
    assert "pending" in csv_text


@pytest.mark.asyncio
async def test_pending_count_drives_the_review_badge():
    await memory_engine.propose(key="room", value="Hall")
    await memory_engine.propose(key="car", value="Civic")
    assert await memory_engine.pending_count() == 2
