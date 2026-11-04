import uuid
from typing import Any


class ComponentType:
    BATTERY = "battery"
    RESISTOR = "resistor"
    LED = "led"
    SWITCH = "switch"
    WIRE = "wire"

class CircuitSimulator:
    def __init__(self):
        self.components: dict[str, dict[str, Any]] = {}
        self.connections: list[dict[str, Any]] = []

    def create_led_circuit(self, battery_voltage: float = 9.0, resistance: float = 330.0) -> dict[str, Any]:
        """Builds a real LED circuit graph: Battery -> Resistor -> LED -> Battery ground."""
        self.components.clear()
        self.connections.clear()
        
        bat_id = f"comp_{uuid.uuid4().hex[:6]}"
        res_id = f"comp_{uuid.uuid4().hex[:6]}"
        led_id = f"comp_{uuid.uuid4().hex[:6]}"

        self.components[bat_id] = {
            "id": bat_id, "type": ComponentType.BATTERY, "name": "9V Battery",
            "voltage": battery_voltage, "pins": ["pos", "neg"]
        }
        self.components[res_id] = {
            "id": res_id, "type": ComponentType.RESISTOR, "name": "330 Ohm Resistor",
            "resistance": resistance, "pins": ["pin1", "pin2"]
        }
        self.components[led_id] = {
            "id": led_id, "type": ComponentType.LED, "name": "Red LED",
            "forward_voltage": 2.0, "max_current_ma": 30.0, "pins": ["anode", "cathode"]
        }

        # Real circuit graph connections
        self.connections = [
            {"from": f"{bat_id}:pos", "to": f"{res_id}:pin1"},
            {"from": f"{res_id}:pin2", "to": f"{led_id}:anode"},
            {"from": f"{led_id}:cathode", "to": f"{bat_id}:neg"}
        ]
        
        simulation_result = self.simulate()
        return {
            "components": list(self.components.values()),
            "connections": self.connections,
            "simulation": simulation_result
        }

    def simulate(self) -> dict[str, Any]:
        """Calculates exact physics & electrical metrics using Ohm's Law (V = I * R)."""
        if not self.components or not self.connections:
            return {"status": "OPEN_CIRCUIT", "current_ma": 0.0, "led_illuminated": False,
                    "error": "No circuit components"}

        battery = next((c for c in self.components.values() if c["type"] == ComponentType.BATTERY), None)
        resistor = next((c for c in self.components.values() if c["type"] == ComponentType.RESISTOR), None)
        led = next((c for c in self.components.values() if c["type"] == ComponentType.LED), None)

        if not battery:
            return {"status": "NO_POWER_SOURCE", "current_ma": 0.0, "led_illuminated": False,
                    "error": "Missing battery source"}

        total_r = resistor["resistance"] if resistor else 0.001
        v_source = battery["voltage"]
        v_led = led["forward_voltage"] if led else 0.0

        if total_r <= 0.01:
            # This model has no internal resistance, so a "short" is a loop whose only
            # resistance is the fallback. Report what the arithmetic actually gives
            # instead of a round number invented to look alarming.
            short_ma = round((v_source - v_led) / total_r * 1000.0, 2) if total_r > 0 else 0.0
            return {
                "status": "SHORT_CIRCUIT",
                "current_ma": short_ma,
                "led_illuminated": False,
                "error": "WARNING: Short circuit detected! High current draw.",
                "note": (
                    "current comes from V/R with R below 0.01 ohm; a real supply has internal "
                    "resistance this model does not have, so treat the figure as 'very high', not measured"
                ) if total_r > 0 else "resistance is exactly zero, which this model cannot divide by",
            }

        # Current I = (V_battery - V_led) / R
        v_net = max(0.0, v_source - v_led)
        current_a = v_net / total_r
        current_ma = current_a * 1000.0
        
        led_on = False
        warning = None
        if led:
            if current_ma >= 5.0 and current_ma <= led.get("max_current_ma", 30.0):
                led_on = True
            elif current_ma > led.get("max_current_ma", 30.0):
                led_on = True
                warning = f"LED current {current_ma:.1f}mA exceeds maximum safe threshold ({led['max_current_ma']}mA)!"

        return {
            "status": "NORMAL_OPERATION",
            "voltage_v": v_source,
            "current_ma": round(current_ma, 2),
            "resistance_ohm": total_r,
            "led_illuminated": led_on,
            "power_mw": round(v_net * current_ma, 2),
            "warning": warning
        }

circuit_simulator = CircuitSimulator()
