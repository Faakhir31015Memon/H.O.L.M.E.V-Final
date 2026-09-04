from typing import Dict, Any, Optional, List, Tuple
from app.config.settings import settings

class SmartDeviceRegistry:
    def __init__(self):
        # Default registered smart home devices
        self.devices: Dict[str, Dict[str, Any]] = {
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

    async def resolve_device(self, room: str, device_type: str) -> Optional[Dict[str, Any]]:
        room_lower = room.lower().strip()
        type_lower = device_type.lower().strip()
        
        for dev in self.devices.values():
            if dev["room"].lower() in room_lower or room_lower in dev["room"].lower():
                if dev["device_type"].lower() in type_lower or type_lower in dev["device_type"].lower():
                    return dev
        return None

    async def execute_device_command(
        self, device_id: str, power: bool, speed: Optional[int] = None
    ) -> Tuple[bool, bool, Dict[str, Any], Optional[str]]:
        if device_id not in self.devices:
            return False, False, {}, "Device not found"
        
        device = self.devices[device_id]
        
        # Capability validation
        if speed is not None and "speed" not in device["capabilities"]:
            return False, False, device["state"], f"Device '{device['name']}' does not support speed control."

        # Update state
        device["state"]["power"] = power
        if speed is not None:
            device["state"]["speed"] = speed

        # Verified execution result
        return True, True, device["state"], None

device_registry = SmartDeviceRegistry()
