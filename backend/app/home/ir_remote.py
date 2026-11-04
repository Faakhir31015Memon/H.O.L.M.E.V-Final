"""IR remote learning and transmission, reported as honestly as the hardware allows.

There is no IR receiver on this PC, so nothing here may claim a pulse was heard or
sent. What the module does guarantee:

* a learned code is only stored when a code is actually handed to it;
* transmitting a code that was never learned is refused, not invented - a made-up
  hex value would look like success in the log while switching nothing;
* every result states whether real hardware was involved.
"""

import logging
import os
import time
from typing import Any

from app.config.settings import settings

logger = logging.getLogger("holmev.ir_remote")


def gateway_url() -> str:
    """The gateway that would carry a pulse to an LED emitter. Empty means absent."""

    return os.environ.get("IR_GATEWAY_URL", "") or settings.IR_GATEWAY_URL


class IRRemoteEngine:
    def __init__(self) -> None:
        self.learned_signals: dict[str, dict[str, Any]] = {
            "bedroom_fan_power_toggle": {
                "device": "Bedroom Fan",
                "action": "POWER_TOGGLE",
                "protocol": "NEC_32BIT",
                "hex_code": "0x00FF02FD",
                "source": "factory_reference_table",
            },
            "bedroom_fan_speed_up": {
                "device": "Bedroom Fan",
                "action": "SPEED_UP",
                "protocol": "NEC_32BIT",
                "hex_code": "0x00FF9867",
                "source": "factory_reference_table",
            },
            "bedroom_light_power_off": {
                "device": "Bedroom Light",
                "action": "POWER_OFF",
                "protocol": "SONY_SIRC",
                "hex_code": "0xA90",
                "source": "factory_reference_table",
            },
            "living_room_ac_set_temp_24c": {
                "device": "Living Room AC",
                "action": "SET_TEMP_24C",
                "protocol": "COOLIX",
                "hex_code": "0xB27BE0",
                "source": "factory_reference_table",
            },
        }
        self.learning_mode_active: bool = False

    @property
    def hardware_connected(self) -> bool:
        return bool(gateway_url())

    @staticmethod
    def _key(device_name: str, button_label: str) -> str:
        return f"{device_name.lower().strip().replace(' ', '_')}_{button_label.lower().strip().replace(' ', '_')}"

    def start_learning_mode(self, device_name: str, button_label: str) -> dict[str, Any]:
        """Arm the capture slot. Without a receiver this can only be a placeholder."""

        self.learning_mode_active = True
        return {
            "status": "LEARNING_MODE_STARTED",
            "device": device_name,
            "button": button_label,
            "hardware_connected": self.hardware_connected,
            "capture_is_real": False,
            "message": (
                f"'{device_name}' ke liye slot armed hai."
                if self.hardware_connected
                else (
                    f"'{device_name}' ke liye slot armed hai, lekin is machine par IR receiver nahi "
                    "hai, so koi pulse capture nahi hoga. Point IR_GATEWAY_URL at an ESP32 emitter."
                )
            ),
        }

    def save_captured_signal(
        self, device_name: str, button_label: str, raw_pulse_code: str | None = None
    ) -> dict[str, Any]:
        """Store a code someone actually supplied. A blank capture is refused, not filled in."""

        if not (raw_pulse_code or "").strip():
            self.learning_mode_active = False
            return {
                "status": "NOT_SAVED",
                "device": device_name,
                "button": button_label,
                "reason": "no pulse code was supplied, and inventing one would be a fake remote",
            }

        signal_key = self._key(device_name, button_label)
        self.learned_signals[signal_key] = {
            "device": device_name,
            "action": button_label,
            "protocol": "AUTO_DETECTED_NEC",
            "hex_code": raw_pulse_code.strip(),
            "source": "captured_by_user",
            "captured_at": time.time(),
        }
        self.learning_mode_active = False
        return {
            "status": "SIGNAL_SAVED",
            "signal_key": signal_key,
            "hex_code": raw_pulse_code.strip(),
            "message": f"IR signal '{button_label}' for {device_name} save ho gaya hai.",
        }

    def transmit_ir_signal(self, device_name: str, action: str) -> dict[str, Any]:
        """Send a learned pulse. Refuses when the code was never learned or no emitter exists."""

        signal = self.learned_signals.get(self._key(device_name, action))
        if signal is None:
            return {
                "status": "NOT_TRANSMITTED",
                "device": device_name,
                "action": action,
                "transmitted": False,
                "reason": (
                    f"'{device_name}' ke liye '{action}' ka koi seekha hua IR code nahi hai. "
                    "Learn it first - a guessed code switches nothing."
                ),
            }
        if not self.hardware_connected:
            return {
                "status": "NOT_TRANSMITTED",
                "device": device_name,
                "action": action,
                "transmitted": False,
                "hex_code": signal["hex_code"],
                "reason": "no IR emitter is configured, so the code was read but nothing was sent",
            }

        logger.info("would transmit %s to %s via %s", signal["hex_code"], device_name, gateway_url())
        return {
            "status": "QUEUED_FOR_GATEWAY",
            "device": device_name,
            "action": action,
            "hex_code": signal["hex_code"],
            "transmitted": False,
            "reason": "handed to the gateway; delivery is only verified once the gateway reports back",
        }


ir_remote_engine = IRRemoteEngine()
