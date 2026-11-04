"""Circuit tools expose the simulator honestly.

The simulator solves one real single-loop LED circuit with Ohm's law, so `verified`
stays false: nothing here measured a breadboard. The old `circuit.create` also took a
`circuit_type` of "series"/"parallel" and silently built an LED circuit regardless,
which is the tool agreeing to something it did not do.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolResult

COMPUTED_NOTE = "arithmetic on a circuit graph inside this process; no physical circuit was measured"
SUPPORTED_TYPES = ("led", "series")


class CreateCircuitInput(BaseModel):
    circuit_type: str = Field(default="led", description="Circuit pattern type: led or series")
    battery_voltage: float = Field(default=9.0, ge=0.0, le=100.0, description="Battery voltage in volts")
    resistance: float = Field(default=330.0, ge=0.0, le=1_000_000.0, description="Series resistor in ohms")


class CreateCircuitTool(BaseTool):
    name = "circuit.create"
    description = "Builds a single-loop battery-resistor-LED graph and computes its operating point."
    category = "circuit"
    permission_level = 1
    input_schema = CreateCircuitInput

    async def _run(
        self, circuit_type: str = "led", battery_voltage: float = 9.0, resistance: float = 330.0, **kwargs: Any
    ) -> ToolResult:
        from app.circuits.simulator import circuit_simulator

        wanted = (circuit_type or "led").strip().lower()
        if wanted not in SUPPORTED_TYPES:
            return ToolResult(
                success=False,
                verified=False,
                error=(
                    f"'{wanted}' cannot be built. This simulator models one series loop "
                    f"(battery -> resistor -> LED), so the supported types are {', '.join(SUPPORTED_TYPES)}."
                ),
                data={"created": False, "supported": list(SUPPORTED_TYPES)},
            )

        data = circuit_simulator.create_led_circuit(battery_voltage=battery_voltage, resistance=resistance)
        return ToolResult(
            success=True,
            verified=False,
            data={**data, "circuit_type": wanted, "note": COMPUTED_NOTE},
            error=None,
        )


class SimulateCircuitInput(BaseModel):
    circuit_id: str = Field(default="current", description="Circuit instance ID (the simulator holds one graph)")


class SimulateCircuitTool(BaseTool):
    name = "circuit.simulate"
    description = "Runs the electrical physics simulator on the circuit graph currently held in memory."
    category = "circuit"
    permission_level = 0
    input_schema = SimulateCircuitInput

    async def _run(self, circuit_id: str = "current", **kwargs: Any) -> ToolResult:
        from app.circuits.simulator import circuit_simulator

        sim_data = circuit_simulator.simulate()
        return ToolResult(
            success=sim_data.get("status") != "OPEN_CIRCUIT",
            verified=False,
            data={**sim_data, "circuit_id": circuit_id, "note": COMPUTED_NOTE},
            error=None,
        )
