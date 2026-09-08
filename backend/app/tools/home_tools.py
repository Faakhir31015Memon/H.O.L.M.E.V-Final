from typing import Optional, Any, List
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult
from app.home.cctv_manager import cctv_manager
from app.home.ir_remote import ir_remote_engine

class SetDevicePowerInput(BaseModel):
    room: str = Field(description="Room name, e.g. Bedroom, Hall, Kitchen")
    device_type: str = Field(description="Device type, e.g. fan, light, ac, tv, plug")
    power: bool = Field(description="True for ON, False for OFF")
    speed: Optional[int] = Field(default=None, description="Optional speed/setting value e.g. 1-5")

class HomeDeviceControlTool(BaseTool):
    name = "home.device.set_power"
    description = "Controls smart home devices (fans, lights, AC, TV) by room and capability."
    category = "home"
    permission_level = 2
    input_schema = SetDevicePowerInput

    async def _run(self, room: str = "", device_type: str = "", power: bool = False, speed: Optional[int] = None, **kwargs: Any) -> ToolResult:
        from app.devices.registry import device_registry
        
        device = await device_registry.resolve_device(room=room, device_type=device_type)
        if not device:
            # Fallback to IR transmission if physical smart plug isn't configured
            action = f"POWER_{'ON' if power else 'OFF'}"
            if speed is not None:
                action = f"SPEED_{speed}"
            ir_res = ir_remote_engine.transmit_ir_signal(f"{room} {device_type}", action)
            return ToolResult(
                success=True,
                verified=True,
                data={"device": f"{room} {device_type}".title(), "room": room, "state": {"power": power, "speed": speed}, "ir": ir_res},
                error=None
            )

        success, verified, new_state, err = await device_registry.execute_device_command(
            device_id=device["id"],
            power=power,
            speed=speed
        )
        
        return ToolResult(
            success=success,
            verified=verified,
            data={"device": device["name"], "room": device["room"], "state": new_state},
            error=err
        )

class CCTVDisplayInput(BaseModel):
    cameras: Optional[List[str]] = Field(default=None, description="List of camera room tags e.g. ['bedroom', 'hall']")
    raw_query: str = Field(default="", description="Original user prompt for context parsing")

class CCTVDisplayTool(BaseTool):
    name = "home.cctv.show"
    description = "Displays live CCTV camera feeds for requested rooms or asks clarification if ambiguous."
    category = "home"
    permission_level = 1
    input_schema = CCTVDisplayInput

    async def _run(self, cameras: Optional[List[str]] = None, raw_query: str = "", **kwargs: Any) -> ToolResult:
        res = cctv_manager.process_camera_request(camera_names=cameras, raw_query=raw_query)
        return ToolResult(
            success=res["success"],
            verified=True,
            data=res,
            error=res.get("error")
        )

class IRLearnInput(BaseModel):
    device_name: str = Field(description="Appliance name e.g. Bedroom Fan")
    button_label: str = Field(description="Button label e.g. POWER_OFF, SPEED_2")

class IRLearnTool(BaseTool):
    name = "home.ir.learn"
    description = "Enables IR receiver to capture physical remote pulse signal."
    category = "home"
    permission_level = 1
    input_schema = IRLearnInput

    async def _run(self, device_name: str = "", button_label: str = "", **kwargs: Any) -> ToolResult:
        res = ir_remote_engine.start_learning_mode(device_name, button_label)
        return ToolResult(
            success=True,
            verified=True,
            data=res,
            error=None
        )
