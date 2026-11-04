"""HTTP surface tests: the API answers from state the brain actually wrote.

These drive the real FastAPI app through TestClient. They deliberately avoid the
streaming endpoint (it stays open by design) and never let a test talk to a real
phone, camera, mail server or model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app
from app.security.undo import undo_engine

client = TestClient(app)

BASE = "/api/v1/brain"


@pytest.fixture(autouse=True)
def no_token_required(monkeypatch):
    monkeypatch.setattr(settings, "API_TOKEN", "", raising=False)


def get(path: str):
    return client.get(f"{BASE}{path}")


def post(path: str, json: dict | None = None, params: dict | None = None):
    return client.post(f"{BASE}{path}", json=json, params=params)


def test_the_brain_surface_is_mounted_and_readable():
    response = get("/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "stop",
        "active_runs",
        "pending_approvals",
        "reversible_actions",
        "has_real_model",
        "capabilities",
        "workspace_root",
    }
    assert body["workspace_root"] == str(Path(settings.WORKSPACE_ROOT))


def test_capabilities_report_the_wiring_that_exists_right_now(monkeypatch):
    """A capability flag must flip with the config, because it is read from it."""

    monkeypatch.setattr(settings, "ALLOW_SYSTEM_POWER_ACTIONS", False)
    monkeypatch.setattr(settings, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_FROM_ADDRESS", "", raising=False)
    monkeypatch.delenv("MOBILE_BRIDGE_URL", raising=False)
    monkeypatch.setattr(settings, "MOBILE_BRIDGE_URL", "", raising=False)

    capabilities = get("/status").json()["capabilities"]
    assert capabilities["power_actions"] is False, "off until the user opts in"
    assert capabilities["email"] is False, "no SMTP server configured"
    assert capabilities["phone_bridge"] is False, "no companion bridge paired"

    monkeypatch.setattr(settings, "ALLOW_SYSTEM_POWER_ACTIONS", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.internal.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_FROM_ADDRESS", "holmev@internal.test", raising=False)
    monkeypatch.setattr(settings, "MOBILE_BRIDGE_URL", "http://127.0.0.1:8899", raising=False)

    after = get("/status").json()["capabilities"]
    assert after["power_actions"] is True
    assert after["email"] is True
    assert after["phone_bridge"] is True
    assert "refuse" in get("/status").json()["capabilities_note"]


def test_a_protected_endpoint_demands_the_token_when_one_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "API_TOKEN", "s3cret-token", raising=False)

    assert client.get(BASE + "/tools").status_code == 401
    assert client.get(BASE + "/tools", headers={"X-HOLMEV-Token": "wrong"}).status_code == 401
    assert client.get(BASE + "/tools", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_stop_never_demands_a_token(monkeypatch):
    """The emergency stop has to work even if the client lost its credential."""

    monkeypatch.setattr(settings, "API_TOKEN", "locked", raising=False)

    assert client.post(BASE + "/stop", params={"reason": "test"}).status_code == 200
    assert client.get(BASE + "/approvals").status_code == 401
    assert client.post(BASE + "/stop/resume", headers={"X-HOLMEV-Token": "locked"}).status_code == 200


def test_tools_are_listed_with_their_real_permission_and_approval_need():
    body = get("/tools").json()
    by_name = {tool["name"]: tool for tool in body["tools"]}

    assert by_name["mobile.phone.call"]["needs_approval"] is True
    assert by_name["web.search"]["needs_approval"] is False
    assert by_name["desktop.system_control"]["permission_level"] == 4
    assert "threed.export_model" in by_name, "the 3D exporter is reachable through the catalog"
    assert body["approval_min_level"] == settings.APPROVAL_MIN_LEVEL


def test_models_and_route_preview_explain_the_choice_they_made():
    models = get("/models").json()
    assert set(models) >= {"serving", "providers", "adapter_health", "has_real_model", "privacy_level"}
    assert all("provider" in model and "name" in model for model in models["serving"])

    preview = post(
        "/route/preview",
        json={"required_capabilities": ["chat"], "complexity": "simple", "privacy_level": "local_only"},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert set(body) == {"decision", "ranking"}
    assert set(body["decision"]) >= {"model", "provider", "reason", "data_leaves_device", "degraded"}
    for entry in body["ranking"]:
        assert set(entry) == {"model", "score", "breakdown", "notes"}


def test_undo_list_and_reversal_through_the_api(isolated_workspace: Path):
    workspace = isolated_workspace
    (workspace / "api_created.txt").write_text("hello", encoding="utf-8")
    before = undo_engine.capture_before("file.delete", {"path": "api_created.txt"})
    record = asyncio.run(
        undo_engine.record(run_id="api_run", approval_id=None, tool="file.delete", params={}, before=before)
    )
    (workspace / "api_created.txt").unlink()

    listed = get("/undo").json()
    assert listed["count"] == len(listed["records"]) >= 1
    entry = next(item for item in listed["records"] if item["undo_id"] == record.id)
    assert entry["kind"] == "deleted" and entry["reversible"] is True

    reversed_result = post(f"/undo/{record.id}")
    assert reversed_result.status_code == 200
    assert reversed_result.json()["reversed"] is True
    assert (workspace / "api_created.txt").read_text(encoding="utf-8") == "hello"

    again = post(f"/undo/{record.id}")
    assert again.status_code == 409
    assert "undone" in again.json()["detail"]

    assert post("/undo/nope-not-real").status_code == 409


def test_cameras_are_listed_without_any_network_call(monkeypatch):
    monkeypatch.setattr(settings, "CAMERAS", "", raising=False)

    body = get("/cameras").json()
    assert body["feeds_verified"] is False
    assert {camera["name"] for camera in body["cameras"]} >= {"Bedroom Camera", "Hall Camera"}
    assert all(camera["has_feed"] is False for camera in body["cameras"]), "no URLs declared, none claimed"
    assert all(camera["feeds_verified"] is False for camera in body["cameras"])


def test_the_scene_endpoint_reads_the_live_scene():
    from app.projects.threed_manager import threed_manager

    threed_manager.objects.clear()
    assert get("/scene").json()["scene"]["objects"] == 0

    threed_manager.create_object("cube")
    body = get("/scene").json()
    assert set(body) == {"objects", "scene", "bounding_box"}
    assert body["scene"]["objects"] == 1
    assert body["objects"][0]["vertices"] == 8
    threed_manager.objects.clear()


def test_audit_is_queryable_and_marks_its_redaction():
    body = get("/audit?limit=5").json()
    assert body["redacted"] is True
    assert isinstance(body["entries"], list)


def test_an_unknown_run_is_a_four_not_an_invented_answer():
    assert get("/runs/run_that_never_happened").status_code == 404
