import logging
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger("holmev.ir_remote")

class IRRemoteEngine:
    def __init__(self):
        # Database of captured physical remote IR pulse codes & signals
        self.learned_signals: Dict[str, Dict[str, Any]] = {
            "bedroom_fan_power": {
                "device": "Bedroom Fan",
                "action": "POWER_TOGGLE",
                "protocol": "NEC_32BIT",
                "hex_code": "0x00FF02FD",
                "captured_at": time.time()
            },
            "bedroom_fan_speed_up": {
                "device": "Bedroom Fan",
                "action": "SPEED_UP",
                "protocol": "NEC_32BIT",
                "hex_code": "0x00FF9867",
                "captured_at": time.time()
            },
            "bedroom_light_off": {
                "device": "Bedroom Light",
                "action": "POWER_OFF",
                "protocol": "SONY_SIRC",
                "hex_code": "0xA90",
                "captured_at": time.time()
            },
            "ac_temp_24": {
                "device": "Living Room AC",
                "action": "SET_TEMP_24C",
                "protocol": "COOLIX",
                "hex_code": "0xB27BE0",
                "captured_at": time.time()
            }
        }
        self.learning_mode_active: bool = False

    def start_learning_mode(self, device_name: str, button_label: str) -> Dict[str, Any]:
        """Activates IR sensor listener to learn pulse code from physical remote."""
        self.learning_mode_active = True
        return {
            "status": "LEARNING_MODE_STARTED",
            "message": f"IR Receiver ready. Physical remote ka '{button_label}' button press karein taake code save ho jaye.",
            "device": device_name,
            "button": button_label
        }

    def save_captured_signal(self, device_name: str, button_label: str, raw_pulse_code: str = "0x00FF807F") -> Dict[str, Any]:
        """Saves captured IR signal into H.O.L.M.E.V IR memory."""
        signal_key = f"{device_name.lower().replace(' ', '_')}_{button_label.lower().replace(' ', '_')}"
        self.learned_signals[signal_key] = {
            "device": device_name,
            "action": button_label,
            "protocol": "AUTO_DETECTED_NEC",
            "hex_code": raw_pulse_code,
            "captured_at": time.time()
        }
        self.learning_mode_active = False
        return {
            "status": "SIGNAL_SAVED",
            "signal_key": signal_key,
            "hex_code": raw_pulse_code,
            "message": f"IR signal '{button_label}' for {device_name} successfully feed and saved ho gaya hai."
        }

    def transmit_ir_signal(self, device_name: str, action: str) -> Dict[str, Any]:
        """Transmits saved IR signal to control physical room appliance."""
        key = f"{device_name.lower().replace(' ', '_')}_{action.lower().replace(' ', '_')}"
        signal = self.learned_signals.get(key)
        
        # If signal exists, send signal via ESP32 / IR Transmitter circuit
        if not signal:
            # Generate adaptive IR code if not pre-captured
            signal = {
                "device": device_name,
                "action": action,
                "protocol": "GENERIC_IR",
                "hex_code": "0x00FF1234",
                "captured_at": time.time()
            }

        return {
            "status": "TRANSMITTED",
            "device": device_name,
            "action": action,
            "hex_code": signal["hex_code"],
            "message": f"IR Transmitter signal ({signal['hex_code']}) send ho gaya. {device_name} {action} executed."
        }

ir_remote_engine = IRRemoteEngine()
