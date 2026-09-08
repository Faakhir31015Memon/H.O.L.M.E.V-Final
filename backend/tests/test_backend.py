import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.tools.registry import tool_registry
from app.permissions.engine import permission_engine
from app.brain.brain import holmev_brain
from python_services.voice.voice_manager import voice_manager
from app.circuits.simulator import circuit_simulator
from app.home.cctv_manager import cctv_manager
from app.home.ir_remote import ir_remote_engine
from app.navigation.route_engine import route_engine
from app.communication.mobile_bridge import mobile_bridge_service

client = TestClient(app)

def test_health_endpoints():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "database" in data["services"]

def test_ready_version_endpoints():
    r1 = client.get("/ready")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ready"

    r2 = client.get("/version")
    assert r2.status_code == 200
    assert "1.0.0" in r2.json()["version"]

@pytest.mark.asyncio
async def test_tool_registry_and_permission_engine():
    tool = tool_registry.get_tool("desktop.create_folder")
    assert tool is not None
    perm = permission_engine.evaluate(tool, {"folder_path": "./test_dir"})
    assert perm.allowed is True

@pytest.mark.asyncio
async def test_circuit_simulator_physics():
    res = circuit_simulator.create_led_circuit(battery_voltage=9.0, resistance=330.0)
    assert res["simulation"]["status"] == "NORMAL_OPERATION"
    assert res["simulation"]["led_illuminated"] is True
    assert res["simulation"]["current_ma"] > 0.0

@pytest.mark.asyncio
async def test_voice_manager_continuous_activation():
    diag1 = voice_manager.get_diagnostics()
    assert diag1.state == "DEACTIVATED"

    res = await voice_manager.handle_user_speech("Holmev chal kaam par lag ja")
    assert res["status"] == "activated"
    
    diag2 = voice_manager.get_diagnostics()
    assert diag2.state == "LISTENING"
    assert diag2.active_audio_sessions == 1

    # Test barge in
    import asyncio
    speak_task = asyncio.create_task(voice_manager.speak("Hello Boss testing speech output"))
    await asyncio.sleep(0.01)
    assert voice_manager.is_speaking is True
    await voice_manager.cancel_tts()
    await speak_task
    assert voice_manager.is_speaking is False
    assert voice_manager.state == "INTERRUPTED"

    res_deact = await voice_manager.handle_user_speech("Holmev so ja")
    assert res_deact["status"] == "deactivated"
    assert voice_manager.get_diagnostics().state == "DEACTIVATED"

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
async def test_ir_remote_and_navigation():
    # Test IR Remote signal learning
    ir_learn = ir_remote_engine.start_learning_mode("Bedroom Fan", "POWER_OFF")
    assert ir_learn["status"] == "LEARNING_MODE_STARTED"

    ir_save = ir_remote_engine.save_captured_signal("Bedroom Fan", "POWER_OFF", "0x00FF02FD")
    assert ir_save["status"] == "SIGNAL_SAVED"

    # Test AR Road Navigation Engine
    nav_res = route_engine.calculate_road_route("Mall Road")
    assert nav_res["success"] is True
    assert nav_res["destination"] == "Mall Road"
    assert len(nav_res["steps"]) > 0

@pytest.mark.asyncio
async def test_mobile_bridge_service():
    wa_res = mobile_bridge_service.send_whatsapp_message("Ali", "Meeting at 5 PM")
    assert wa_res["status"] == "SENT"

    call_res = mobile_bridge_service.make_phone_call("Ali")
    assert call_res["status"] == "CALLING"
