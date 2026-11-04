"""Smart-home tools: registry state is the only proof, and no device is invented.

The old version had a fallback that "controlled" any appliance the registry did not
know about by sending a made-up IR code, then returned `verified=True`. That is the
single most damaging shape an assistant can have: it reports a physical act that no
hardware performed. Now:

* a device the registry does not know is reported as unknown, not improvised;
* a real command is followed by the registry's own state, which the verification
  engine reads back separately;
* `verified` is only ever set by the engine that checked, never asserted here.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.home.cctv_manager import cctv_manager
from app.home.ir_remote import ir_remote_engine
from app.tools.base import BaseTool, ToolResult


class SetDevicePowerInput(BaseModel):
    room: str = Field(description="Room name, e.g. Bedroom, Hall, Kitchen")
    device_type: str = Field(description="Device type, e.g. fan, light, ac, tv, plug")
    power: bool = Field(description="True for ON, False for OFF")
    speed: int | None = Field(default=None, description="Optional speed/setting value e.g. 1-5")


class HomeDeviceControlTool(BaseTool):
    name = "home.device.set_power"
    description = "Controls smart home devices (fans, lights, AC) that are registered on this device."
    category = "home"
    permission_level = 2
    input_schema = SetDevicePowerInput

    async def _run(
        self, room: str = "", device_type: str = "", power: bool = False,
        speed: int | None = None, **kwargs: Any
    ) -> ToolResult:
        from app.devices.registry import device_registry

        device = await device_registry.resolve_device(room=room, device_type=device_type)
        if device is None:
            attempted = f"{room} {device_type}".strip().title() or "that device"
            ir_res = ir_remote_engine.transmit_ir_signal(attempted, f"POWER_{'ON' if power else 'OFF'}")
            return ToolResult(
                success=False,
                verified=False,
                error=(
                    f"'{attempted}' is not registered on this device, so nothing was switched. "
                    f"IR said: {ir_res.get('reason', ir_res.get('status'))}. "
                    "Add it to the device registry (or configure an IR emitter) and ask again."
                ),
                data={"device": attempted, "ir": ir_res},
            )

        success, reached, new_state, err = await device_registry.execute_device_command(
            device_id=device["id"], power=power, speed=speed
        )
        if err:
            return ToolResult(success=False, verified=False, error=err, data={"device": device["name"]})

        # The registry's state after the call is what the verification engine reads
        # back; `verified` below is deliberately left for that check to decide.
        return ToolResult(
            success=success,
            verified=False,
            data={
                "device": device["name"],
                "room": device["room"],
                "device_type": device["device_type"],
                "state": new_state,
                "protocol": device.get("protocol"),
                "reached_hardware": reached,
                "note": (
                    "state updated in the registry"
                    if reached
                    else "registry state only: HOME_DEVICE_MODE is SIMULATED, so no appliance was switched"
                ),
            },
        )


class CCTVDisplayInput(BaseModel):
    cameras: list[str] | None = Field(default=None, description="List of camera room tags e.g. ['bedroom', 'hall']")
    raw_query: str = Field(default="", description="Original user prompt for context parsing")


class CCTVDisplayTool(BaseTool):
    name = "home.cctv.show"
    description = "Shows the CCTV feeds for requested rooms, or asks which room if the request is ambiguous."
    category = "home"
    permission_level = 1
    input_schema = CCTVDisplayInput

    async def _run(self, cameras: list[str] | None = None, raw_query: str = "", **kwargs: Any) -> ToolResult:
        res = cctv_manager.process_camera_request(camera_names=cameras, raw_query=raw_query)
        return ToolResult(
            success=res["success"],
            verified=False,
            data=res,
            error=res.get("error"),
        )


class IRLearnInput(BaseModel):
    device_name: str = Field(description="Appliance name e.g. Bedroom Fan")
    button_label: str = Field(description="Button label e.g. POWER_OFF, SPEED_2")


class IRLearnTool(BaseTool):
    name = "home.ir.learn"
    description = "Arms the IR receiver to capture a pulse from the physical remote."
    category = "home"
    permission_level = 1
    input_schema = IRLearnInput

    async def _run(self, device_name: str = "", button_label: str = "", **kwargs: Any) -> ToolResult:
        res = ir_remote_engine.start_learning_mode(device_name, button_label)
        capture_is_real = bool(res.get("capture_is_real"))
        return ToolResult(
            success=True,
            verified=False,
            data=res,
            error=None if capture_is_real else "armed, but this machine has no IR receiver to capture with",
        )
