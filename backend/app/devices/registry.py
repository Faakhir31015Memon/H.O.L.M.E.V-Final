import os
from typing import Any

from app.config.settings import settings


def hardware_is_real() -> bool:
    """Whether a command here can reach a physical appliance at all."""

    mode = (os.environ.get("HOME_DEVICE_MODE") or settings.HOME_DEVICE_MODE or "").upper()
    return mode not in {"", "SIMULATED", "MOCK", "DEMO"}


class SmartDeviceRegistry:
    """In-memory device state.

    With HOME_DEVICE_MODE="SIMULATED" (the default) this registry is the only
    thing that changes: no MQTT/IR packet leaves the machine. Every reader that
    needs to know the difference uses `hardware_is_real`.
    """

    def __init__(self):
        # Default registered smart home devices
        self.devices: dict[str, dict[str, Any]] = {
            "dev_bed_fan": {
                "id": "dev_bed_fan",
                "name": "Bedroom Fan",
                "room": "Bedroom",
                "device_type": "fan",
                "protocol": "mqtt",
                "capabilities": ["power", "speed"],
                "state": {"power": True, "speed": 1}
            },
            "dev_bed_light": {
                "id": "dev_bed_light",
                "name": "Bedroom Light",
                "room": "Bedroom",
                "device_type": "light",
                "protocol": "mqtt",
                "capabilities": ["power", "brightness"],
                "state": {"power": True, "brightness": 100}
            },
            "dev_hall_fan": {
                "id": "dev_hall_fan",
                "name": "Hall Fan",
                "room": "Hall",
                "device_type": "fan",
                "protocol": "mqtt",
                "capabilities": ["power", "speed"],
                "state": {"power": False, "speed": 0}
            },
            "dev_hall_light": {
                "id": "dev_hall_light",
                "name": "Hall Light",
                "room": "Hall",
                "device_type": "light",
                "protocol": "mqtt",
                "capabilities": ["power"],
                "state": {"power": True}
            },
            "dev_bed_ac": {
                "id": "dev_bed_ac",
                "name": "Bedroom AC",
                "room": "Bedroom",
                "device_type": "ac",
                "protocol": "ir",
                "capabilities": ["power", "temperature"],
                "state": {"power": False, "temperature": 24}
            }
        }

    async def resolve_device(self, room: str, device_type: str) -> dict[str, Any] | None:
        room_lower = room.lower().strip()
        type_lower = device_type.lower().strip()
        
        for dev in self.devices.values():
            room_matches = dev["room"].lower() in room_lower or room_lower in dev["room"].lower()
            type_matches = dev["device_type"].lower() in type_lower or type_lower in dev["device_type"].lower()
            if room_matches and type_matches:
                return dev
        return None

    async def execute_device_command(
        self, device_id: str, power: bool, speed: int | None = None
    ) -> tuple[bool, bool, dict[str, Any], str | None]:
        """Update the registry's state and report whether real hardware saw it.

        Returns (accepted, reached_hardware, state, error). The second value is the
        honest one: with HOME_DEVICE_MODE=SIMULATED nothing leaves this machine, so
        no caller may describe it as a physical switch.
        """

        if device_id not in self.devices:
            return False, False, {}, "Device not found"

        device = self.devices[device_id]

        if speed is not None and "speed" not in device["capabilities"]:
            return False, False, device["state"], f"Device '{device['name']}' does not support speed control."

        device["state"]["power"] = power
        if speed is not None:
            device["state"]["speed"] = speed

        return True, hardware_is_real(), dict(device["state"]), None


device_registry = SmartDeviceRegistry()
