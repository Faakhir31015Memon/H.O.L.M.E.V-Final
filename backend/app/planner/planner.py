import uuid
import time
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
from app.tools.registry import tool_registry
from app.permissions.engine import permission_engine, PermissionCheckResult

class TaskStep(BaseModel):
    step_id: str
    tool_name: str
    arguments: Dict[str, Any]
    status: str = "PENDING"  # PENDING, EXECUTING, COMPLETED, FAILED, CANCELLED
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    verified: bool = False
    duration_ms: int = 0

class ExecutionPlan(BaseModel):
    plan_id: str
    user_query: str
    steps: List[TaskStep]
    status: str = "CREATED"

class AgentPlanner:
    async def create_and_execute_plan(self, user_query: str, plan_spec: Dict[str, Any]) -> Tuple[ExecutionPlan, Dict[str, Any]]:
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        tool_name = plan_spec.get("tool")
        arguments = plan_spec.get("arguments", {})

        step = TaskStep(
            step_id=f"step_1_{uuid.uuid4().hex[:4]}",
            tool_name=tool_name,
            arguments=arguments
        )
        plan = ExecutionPlan(plan_id=plan_id, user_query=user_query, steps=[step])

        tool = tool_registry.get_tool(tool_name)
        if not tool:
            step.status = "FAILED"
            step.error = f"Tool '{tool_name}' is not registered."
            plan.status = "FAILED"
            return plan, {"success": False, "verified": False, "error": step.error}

        # Permission check
        perm_check: PermissionCheckResult = permission_engine.evaluate(tool=tool, arguments=arguments)
        if not perm_check.allowed:
            step.status = "FAILED"
            step.error = perm_check.reason
            plan.status = "BLOCKED"
            return plan, {"success": False, "verified": False, "error": perm_check.reason}

        # Execution
        step.status = "EXECUTING"
        plan.status = "RUNNING"
        tool_result = await tool.execute(**arguments)

        step.result = tool_result.data
        step.error = tool_result.error
        step.verified = tool_result.verified
        step.duration_ms = tool_result.duration_ms

        if tool_result.success:
            step.status = "COMPLETED"
            plan.status = "COMPLETED"
        else:
            step.status = "FAILED"
            plan.status = "FAILED"

        return plan, tool_result.model_dump()

agent_planner = AgentPlanner()
