from typing import Any
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult

class CreateCircuitInput(BaseModel):
    circuit_type: str = Field(default="led", description="Circuit pattern type: led, series, parallel")

class CreateCircuitTool(BaseTool):
    name = "circuit.create"
    description = "Creates an electrical circuit graph and executes Python simulation math."
    category = "circuit"
    permission_level = 1
    input_schema = CreateCircuitInput

    async def _run(self, circuit_type: str = "led", **kwargs: Any) -> ToolResult:
        from app.circuits.simulator import circuit_simulator
        
        data = circuit_simulator.create_led_circuit()
        return ToolResult(
            success=True,
            verified=True,
            data=data,
            error=None
        )

class SimulateCircuitInput(BaseModel):
    circuit_id: str = Field(default="current", description="Circuit instance ID")

class SimulateCircuitTool(BaseTool):
    name = "circuit.simulate"
    description = "Runs the electrical physics simulator engine on the current circuit graph."
    category = "circuit"
    permission_level = 0
    input_schema = SimulateCircuitInput

    async def _run(self, circuit_id: str = "current", **kwargs: Any) -> ToolResult:
        from app.circuits.simulator import circuit_simulator
        
        sim_data = circuit_simulator.simulate()
        return ToolResult(
            success=True,
            verified=True,
            data=sim_data,
            error=None
        )
