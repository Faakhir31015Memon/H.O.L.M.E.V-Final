import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.tools.registry import tool_registry
from app.permissions.engine import permission_engine
from app.brain.brain import holmev_brain
from python_services.voice.voice_manager import voice_manager
from app.circuits.simulator import circuit_simulator

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
async def test_brain_end_to_end_intent():
    res = await holmev_brain.process_user_request("Bedroom fan speed 2 kar do")
    assert res["tool"] == "home.device.set_power"
    assert res["result"]["success"] is True
    assert res["result"]["verified"] is True
    assert "Bedroom Fan ON" in res["spoken_response"] or "ON" in res["spoken_response"]
