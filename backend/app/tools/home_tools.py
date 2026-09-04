from typing import Optional
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult

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

    async def _run(self, room: str, device_type: str, power: bool, speed: Optional[int] = None) -> ToolResult:
        from app.devices.registry import device_registry
        
        device = await device_registry.resolve_device(room=room, device_type=device_type)
        if not device:
            return ToolResult(
                success=False,
                verified=False,
                data=None,
                error=f"No matching registered device '{device_type}' found in room '{room}'."
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
