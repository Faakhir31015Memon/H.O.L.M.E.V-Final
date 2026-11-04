import httpx
import pytest
from fastapi.testclient import TestClient
from python_services.voice.voice_manager import voice_manager

from app.circuits.simulator import circuit_simulator
from app.communication.mobile_bridge import mobile_bridge_service
from app.config.settings import settings
from app.home import cctv_manager as cctv_module
from app.home.cctv_manager import cctv_manager, declared_urls
from app.home.ir_remote import ir_remote_engine
from app.main import app
from app.navigation import route_engine as route_engine_module
from app.navigation.route_engine import route_engine
from app.tools.registry import tool_registry

client = TestClient(app)

def test_health_endpoints():
    """Health reports what it probed, so a machine with no model says degraded."""

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    by_name = {check["name"]: check for check in data["checks"]}
    assert data["services"]["database"] == "online"
    assert by_name["voice"]["status"] in ("online", "idle", "unavailable")
    assert "camera" not in by_name, "a health poll must not reach for the camera"

    if by_name["models"]["status"] != "online":
        assert data["status"] == "degraded"
        assert any("ollama pull" in reason for reason in data["reasons"]), data["reasons"]

    r2 = client.get("/ready")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ready"

    r3 = client.get("/version")
    assert r3.status_code == 200
    assert "1.0.0" in r3.json()["version"]

@pytest.mark.asyncio
async def test_registered_tools_carry_their_own_permission_level():
    """The level comes from the tool class, so no caller can lower it at runtime."""

    folder_tool = tool_registry.get_tool("desktop.create_folder")
    assert folder_tool is not None
    assert tool_registry.permission_level_of("desktop.create_folder") == folder_tool.permission_level

    call_tool = tool_registry.get_tool("mobile.phone.call")
    assert call_tool is not None
    assert call_tool.permission_level >= settings.APPROVAL_MIN_LEVEL, "dialling must ask first"

@pytest.mark.asyncio
async def test_circuit_simulator_physics():
    res = circuit_simulator.create_led_circuit(battery_voltage=9.0, resistance=330.0)
    assert res["simulation"]["status"] == "NORMAL_OPERATION"
    assert res["simulation"]["led_illuminated"] is True
    assert res["simulation"]["current_ma"] > 0.0

@pytest.mark.asyncio
async def test_voice_mode_refuses_without_a_microphone(monkeypatch):
    """Activation is a hardware promise: no recogniser means no listening, said plainly."""

    from python_services.voice import speech_io

    monkeypatch.setattr(
        speech_io.recognizer, "_dependency_error", lambda: "faster-whisper is not installed"
    )
    monkeypatch.setattr(speech_io.synthesizer, "backend", None)

    diag = voice_manager.get_diagnostics()
    assert diag.state == "DEACTIVATED"
    assert diag.stt_connected is False, "the mic light must follow the real dependency, not a constant"
    assert diag.input_level == 0.0, "an unmeasured level would be a fabricated meter"

    res = await voice_manager.handle_user_speech("Holmev chal kaam par lag ja")
    assert res["status"] == "not_activated"
    assert "faster-whisper" in res["voice_mode"]["reason"]
    assert "pip install" in res["voice_mode"]["install"]
    assert voice_manager.get_diagnostics().microphone_status == "CLOSED"


@pytest.mark.asyncio
async def test_voice_activation_and_barge_in(monkeypatch):
    """With a working mic it listens; an interruption stops the utterance mid-sentence.

    The synthesiser is a stub here on purpose - a test that made real sound would
    be worse than one that skipped.
    """

    import asyncio

    from python_services.voice import speech_io

    monkeypatch.setattr(speech_io.recognizer, "_dependency_error", lambda: None)

    started = asyncio.Event()
    stoppers: list[asyncio.Event] = []

    async def fake_speak(text: str, *, rate: int = 0) -> speech_io.SynthesisResult:
        stopper = asyncio.Event()
        stoppers.append(stopper)
        started.set()
        await stopper.wait()
        return speech_io.SynthesisResult(True, "stub", "stopped by barge-in")

    def fake_cancel() -> int:
        if not stoppers:
            return 0
        stoppers[-1].set()
        return 1

    monkeypatch.setattr(speech_io.synthesizer, "speak", fake_speak)
    monkeypatch.setattr(speech_io.synthesizer, "cancel", fake_cancel)
    monkeypatch.setattr(speech_io.synthesizer, "backend", "stub")

    activation = await voice_manager.activate_continuous_voice()
    assert activation["activated"] is True

    diag = voice_manager.get_diagnostics()
    assert diag.state == "LISTENING"
    assert diag.microphone_status == "OPEN"
    assert diag.active_audio_sessions == 1

    speak_task = asyncio.create_task(voice_manager.speak("Hello Boss testing speech output"))
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert voice_manager.is_speaking is True
    await voice_manager.cancel_tts()
    await speak_task
    assert voice_manager.is_speaking is False
    assert voice_manager.state == "INTERRUPTED"

    res_deact = await voice_manager.handle_user_speech("Holmev so ja")
    assert res_deact["status"] == "deactivated"
    assert voice_manager.get_diagnostics().state == "DEACTIVATED"
    assert voice_manager.get_diagnostics().microphone_status == "CLOSED"

@pytest.mark.asyncio
async def test_cctv_manager_disambiguation():
    # Test ambiguous prompt asking for CCTV
    res_ambiguous = cctv_manager.process_camera_request(raw_query="CCTV camera dikhao")
    assert res_ambiguous["action_required"] == "DISAMBIGUATION_NEEDED"
    assert "Konsa wala camera dikhaoon?" in res_ambiguous["question"]

    # Test specific single room camera request
    res_bedroom = cctv_manager.process_camera_request(camera_names=["bedroom"])
    assert res_bedroom["action_required"] == "DISPLAY_FEED"
    assert len(res_bedroom["active_streams"]) == 1
    assert res_bedroom["active_streams"][0]["name"] == "Bedroom Camera"

    # Test multi-room camera request
    res_multi = cctv_manager.process_camera_request(camera_names=["bedroom", "hall"])
    assert res_multi["action_required"] == "DISPLAY_FEED"
    assert len(res_multi["active_streams"]) == 2
    assert res_multi["mode"] == "MULTI_VIEW"

@pytest.mark.asyncio
async def test_camera_status_only_comes_from_an_actual_probe(monkeypatch):
    monkeypatch.setattr(settings, "CAMERAS", "", raising=False)
    cctv_manager.refresh()

    listed = cctv_manager.process_camera_request(camera_names=["bedroom"])
    assert listed["feeds_verified"] is False
    assert listed["active_streams"][0]["has_feed"] is False
    assert "configure nahi hai" in listed["message"]

    probed = await cctv_manager.probe(["bedroom"])
    assert probed["results"]["bedroom"] == "no stream URL is configured for it"
    assert cctv_manager.cameras["bedroom"]["status"] == "NO_URL"


@pytest.mark.asyncio
async def test_a_camera_that_answers_is_called_online_and_a_dead_one_is_not(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    calls: list[str] = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, follow_redirects=False):
            calls.append(url)
            if "dead" in url:
                raise httpx.ConnectError("no route to host")
            return FakeResponse(404 if "broken" in url else 200)

    monkeypatch.setattr(
        settings,
        "CAMERAS",
        '{"bedroom": "http://127.0.0.1:8080/live", "hall": "http://dead/cam", "kitchen": "rtsp://192.168.1.9/cam"}',
    )
    monkeypatch.setattr(cctv_module.httpx, "AsyncClient", FakeClient)

    result = await cctv_manager.probe()

    assert result["probed"] is True
    assert result["results"]["hall"].startswith("unreachable")
    assert cctv_manager.cameras["bedroom"]["status"] == "ONLINE"
    assert cctv_manager.cameras["bedroom"]["feeds_verified"] is True
    assert cctv_manager.cameras["hall"]["status"] == "OFFLINE"
    assert cctv_manager.cameras["kitchen"]["status"] == "NOT_PROBEABLE"
    assert cctv_manager.cameras["office"]["status"] == "NO_URL"
    assert calls == ["http://127.0.0.1:8080/live", "http://dead/cam"]

    broken = cctv_manager.process_camera_request(camera_names=["bedroom", "hall"])
    assert broken["feeds_verified"] is False, "displaying a feed is not the same as proving it"


@pytest.mark.asyncio
async def test_malformed_camera_config_is_reported_not_ignored(monkeypatch):
    monkeypatch.setattr(settings, "CAMERAS", "{not json", raising=False)
    urls = declared_urls()
    assert "_error" in urls
    cctv_manager.refresh()
    assert cctv_manager.cameras["bedroom"]["stream_url"] is None


@pytest.mark.asyncio
async def test_ir_remote_stores_only_what_it_is_given():
    ir_learn = ir_remote_engine.start_learning_mode("Bedroom Fan", "POWER_OFF")
    assert ir_learn["status"] == "LEARNING_MODE_STARTED"
    assert ir_learn["capture_is_real"] is False

    saved = ir_remote_engine.save_captured_signal("Bedroom Fan", "POWER_OFF", "0x00FF02FD")
    assert saved["status"] == "SIGNAL_SAVED"

    blank = ir_remote_engine.save_captured_signal("Bedroom Fan", "SLEEP")
    assert blank["status"] == "NOT_SAVED"

    sent = ir_remote_engine.transmit_ir_signal("Bedroom Fan", "POWER_OFF")
    assert sent["status"] == "NOT_TRANSMITTED"
    assert sent["transmitted"] is False


@pytest.mark.asyncio
async def test_navigation_refuses_without_a_routing_server(monkeypatch):
    """No OSRM means no route: the engine must not print an invented distance."""

    monkeypatch.delenv("OSRM_BASE_URL", raising=False)
    monkeypatch.setattr(settings, "OSRM_BASE_URL", "")

    nav = await route_engine.calculate_road_route("Mall Road")
    assert nav["success"] is False
    assert nav["action_required"] == "MAP_BACKEND_MISSING"
    assert "route" in nav["reason"].lower() or "routing" in nav["reason"].lower()

    empty = await route_engine.calculate_road_route("")
    assert empty["action_required"] == "DESTINATION_NEEDED"


@pytest.mark.asyncio
async def test_navigation_reports_what_the_routing_server_said(monkeypatch):
    """Coordinates in, real numbers out - and the numbers come from the response."""

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "code": "Ok",
                "routes": [
                    {
                        "distance": 8425.0,
                        "duration": 1080.0,
                        "geometry": {"coordinates": [[73.04, 33.58], [73.09, 33.61], [73.14, 33.63]]},
                        "legs": [
                            {
                                "steps": [
                                    {"distance": 400.0, "name": "Main Boulevard",
                                     "maneuver": {"type": "depart", "modifier": "north"}},
                                    {"distance": 8025.0, "name": "Expressway",
                                     "maneuver": {"type": "arrive", "modifier": "right"}},
                                ]
                            }
                        ],
                    }
                ],
            }

    calls: list[str] = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setenv("OSRM_BASE_URL", "http://127.0.0.1:5000")
    monkeypatch.setattr(route_engine_module.httpx, "AsyncClient", FakeClient)

    nav = await route_engine.calculate_road_route("33.63,73.14", origin="33.58,73.04")

    assert nav["success"] is True
    assert nav["total_distance"] == "8.4 km"
    assert nav["estimated_time"] == "18 min"
    assert nav["steps"][0]["instruction"].startswith("Head out")
    assert len(nav["hologram_path_3d"]) >= 2
    assert calls and calls[0].startswith("http://127.0.0.1:5000/route/v1/driving/73.04,33.58;73.14,33.63")


@pytest.mark.asyncio
async def test_phone_actions_refuse_without_a_paired_bridge(monkeypatch):
    monkeypatch.delenv("MOBILE_BRIDGE_URL", raising=False)
    monkeypatch.setattr(settings, "MOBILE_BRIDGE_URL", "")

    wa = await mobile_bridge_service.send_whatsapp_message("Ali", "Meeting at 5 PM")
    assert wa["status"] == "NOT_SENT"
    assert wa["sent"] is False
    assert "MOBILE_BRIDGE_URL" in wa["reason"]

    call = await mobile_bridge_service.make_phone_call("Ali")
    assert call["called"] is False

    gallery = await mobile_bridge_service.fetch_mobile_gallery_image("latest")
    assert gallery["retrieved"] is False
    assert "image_url" not in gallery, "no stock photo may be passed off as the user's gallery"


@pytest.mark.asyncio
async def test_email_needs_smtp_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    monkeypatch.setattr(settings, "SMTP_FROM_ADDRESS", "")

    refused = await mobile_bridge_service.send_email("boss@example.com", "hi", "body")
    assert refused["status"] == "NOT_SENT"
    assert "SMTP_HOST" in refused["reason"]

    bad = await mobile_bridge_service.send_email("not-an-address", "hi", "body")
    assert bad["sent"] is False
    assert "not an email address" in bad["reason"]
