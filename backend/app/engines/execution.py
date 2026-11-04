"""Execution engine: the only place in the system that is allowed to touch the world.

Every rule that matters is enforced here, not suggested to the model:
    * the permission level is re-read from the registered tool, never from the plan
    * anything at L2+ needs a fresh, parameter-bound approval that is burned on use
    * every path parameter is resolved by the path guard before the tool sees it
    * the emergency stop is checked before each action, and a stopped run cannot resume
    * each action is audited, and consequential ones leave an undo record behind
    * a step is only "done" when the verification engine confirms it
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import settings
from app.engines.types import Plan, PlanStep, ToolOutcome, VerificationResult
from app.engines.verification import verification_engine
from app.security.approvals import ApprovalRejected, approval_service, canonical_param_hash
from app.security.audit import audit_log
from app.security.path_guard import PathRejected, guard, workspace_root
from app.security.stop import StopEngaged, emergency_stop
from app.security.undo import handles_reversible_action, undo_engine
from app.tools.registry import tool_registry

logger = logging.getLogger("holmev.engines.execution")

PATH_PARAM_KEYS = ("path", "file_path", "folder_path", "directory", "target_path", "destination", "save_path")


@dataclass
class StepExecution:
    step_id: str
    tool: str | None
    params: dict[str, Any]
    permission_level: int
    status: str = "pending"
    outcome: ToolOutcome | None = None
    verification: VerificationResult | None = None
    approval_id: str | None = None
    attempts: int = 0
    error: str | None = None
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "params": self.params,
            "permission_level": self.permission_level,
            "status": self.status,
            "attempts": self.attempts,
            "approval_id": self.approval_id,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "success": bool(self.outcome and self.outcome.success),
            "verified": bool(self.verification and self.verification.verified),
            "independently_verified": bool(self.verification and self.verification.independent),
            "verification": list(self.verification.checks) if self.verification else [],
            "verification_reason": self.verification.reason if self.verification else None,
            "result": (self.outcome.data or {}) if self.outcome else {},
        }


@dataclass
class ExecutionReport:
    executions: list[StepExecution] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    cancelled: bool = False
    stop_reason: str | None = None

    def by_step(self) -> dict[str, ToolOutcome]:
        return {e.step_id: e.outcome for e in self.executions if e.outcome is not None}

    def verifications(self) -> dict[str, VerificationResult]:
        return {e.step_id: e.verification for e in self.executions if e.verification is not None}

    @property
    def all_done(self) -> bool:
        return all(e.status in ("succeeded", "failed", "blocked", "skipped") for e in self.executions)

    @property
    def worst(self) -> StepExecution | None:
        for status in ("failed", "blocked", "skipped"):
            match = next((e for e in self.executions if e.status == status), None)
            if match:
                return match
        return None


class ExecutionEngine:
    def plan_signature(self, plan: Plan) -> dict[str, str]:
        return {step.id: canonical_param_hash(step.tool or "", step.params) for step in plan.steps}

    async def run_plan(
        self,
        plan: Plan,
        *,
        run_id: str,
        session_id: str,
        control: Any | None = None,
        grants: dict[str, str] | None = None,
        refusals: dict[str, str] | None = None,
    ) -> ExecutionReport:
        """Execute in dependency order, pausing the moment something needs the user.

        `grants` maps an approved parameter hash to its approval id; `refusals`
        maps a denied one to the reason, so a denied action is never re-asked.
        """

        report = ExecutionReport()
        grants = dict(grants or {})
        refusals = dict(refusals or {})
        done_ids: set[str] = set()
        attempted: set[str] = set()

        while True:
            ready = [step for step in plan.ready_steps(done_ids) if step.id not in attempted]
            if not ready:
                break
            for step in ready:
                attempted.add(step.id)
                execution = await self._execute_step(step, run_id=run_id, session_id=session_id,
                                                    control=control, grants=grants, refusals=refusals)
                report.executions.append(execution)
                if execution.status == "succeeded":
                    done_ids.add(execution.step_id)
                elif execution.status == "awaiting_approval":
                    report.pending_approvals.append(
                        {
                            "step_id": execution.step_id,
                            "tool": execution.tool,
                            "params": execution.params,
                            "permission_level": execution.permission_level,
                            "approval_id": execution.approval_id,
                        }
                    )
                    self._skip_dependents(plan, execution.step_id, report, done_ids, attempted)
                    return report
                elif execution.status in ("cancelled",):
                    report.cancelled = True
                    report.stop_reason = execution.error
                    return report
                else:
                    self._skip_dependents(plan, execution.step_id, report, done_ids, attempted)

        for step in plan.steps:
            if step.id not in attempted:
                report.executions.append(
                    StepExecution(
                        step_id=step.id, tool=step.tool, params=step.params,
                        permission_level=step.required_permission, status="skipped",
                        error="a step it depends on did not complete",
                    )
                )
        return report

    @staticmethod
    def _skip_dependents(
        plan: Plan, step_id: str, report: ExecutionReport, done_ids: set[str], attempted: set[str]
    ) -> None:
        for step in plan.steps:
            if step.id != step_id and step_id in step.depends_on and step.id not in attempted:
                attempted.add(step.id)
                report.executions.append(
                    StepExecution(
                        step_id=step.id, tool=step.tool, params=step.params,
                        permission_level=step.required_permission, status="skipped",
                        error=f"skipped because step '{step_id}' did not complete",
                    )
                )
                ExecutionEngine._skip_dependents(plan, step.id, report, done_ids, attempted)

    async def _execute_step(
        self,
        step: PlanStep,
        *,
        run_id: str,
        session_id: str,
        control: Any | None,
        grants: dict[str, str],
        refusals: dict[str, str],
    ) -> StepExecution:
        tool = tool_registry.get_tool(step.tool or "")
        permission_level = tool_registry.permission_level_of(step.tool or "")
        if permission_level is None:
            permission_level = step.required_permission
        execution = StepExecution(
            step_id=step.id, tool=step.tool, params=dict(step.params),
            permission_level=int(permission_level if permission_level is not None else 4),
        )

        if not step.tool:
            execution.status = "skipped"
            execution.error = "this step needed no tool"
            return execution

        if tool is None:
            execution.status = "blocked"
            execution.error = f"Tool '{step.tool}' is not registered on this device."
            await audit_log.record(
                action="tool.blocked", outcome="blocked", run_id=run_id, tool=step.tool,
                params=step.params, permission_level=execution.permission_level, error=execution.error,
            )
            return execution

        try:
            emergency_stop.guard(run_id)
        except StopEngaged as exc:
            execution.status = "cancelled"
            execution.error = str(exc)
            return execution

        if control is not None and control.cancelled:
            execution.status = "cancelled"
            execution.error = "run cancelled"
            return execution

        # Levels come from the tool; a plan step that asked for less still pays the tool's price.
        if execution.permission_level < step.required_permission:
            execution.permission_level = step.required_permission

        try:
            self._check_paths(step.params)
        except PathRejected as exc:
            execution.status = "blocked"
            execution.error = f"path refused: {exc.reason}"
            await audit_log.record(
                action="tool.blocked", outcome="blocked", run_id=run_id, tool=step.tool,
                params=step.params, permission_level=execution.permission_level, error=execution.error,
            )
            return execution

        param_hash = canonical_param_hash(step.tool or "", step.params)
        approval_id: str | None = None

        if execution.permission_level >= settings.APPROVAL_MIN_LEVEL:
            grant_id = grants.pop(param_hash, None)
            if grant_id is None:
                refused = refusals.get(param_hash)
                if refused:
                    execution.status = "blocked"
                    execution.error = refused
                    await audit_log.record(
                        action="approval.respected_denial", outcome="denied", run_id=run_id, tool=step.tool,
                        params=step.params, permission_level=execution.permission_level, error=refused,
                    )
                    return execution
                record = await approval_service.create(
                    tool=step.tool or "",
                    params=step.params,
                    permission_level=execution.permission_level,
                    summary=_summary(step),
                    run_id=run_id,
                    step_id=step.id,
                )
                execution.status = "awaiting_approval"
                execution.approval_id = record.id
                await audit_log.record(
                    action="approval.requested", outcome="pending", actor="brain", run_id=run_id,
                    tool=step.tool, params=step.params, permission_level=execution.permission_level,
                    approval_id=record.id,
                )
                return execution
            try:
                consumed = await approval_service.consume(grant_id, tool=step.tool or "", params=step.params)
                approval_id = consumed.id
            except ApprovalRejected as exc:
                execution.status = "blocked"
                execution.error = str(exc)
                await audit_log.record(
                    action="approval.rejected", outcome="denied", run_id=run_id, tool=step.tool,
                    params=step.params, permission_level=execution.permission_level,
                    approval_id=grant_id, error=str(exc),
                )
                return execution

        max_attempts = 1 + max(0, int(step.max_retries or 0))
        started = time.perf_counter()
        # Captured before the first attempt: a retry must not overwrite the pre-image
        # with the damage the first attempt already did.
        reversible = handles_reversible_action(step.tool or "")
        before = undo_engine.capture_before(step.tool or "", step.params) if reversible else {}
        for attempt in range(max_attempts):
            execution.attempts = attempt + 1
            outcome = await self._invoke(tool, step.params)
            execution.outcome = outcome
            verification = verification_engine.verify(step, outcome)
            execution.verification = verification
            if outcome.success and verification.verified:
                execution.status = "succeeded"
                break
            execution.error = outcome.error or verification.reason
            if attempt + 1 < max_attempts:
                logger.info("step %s attempt %s unverified, retrying", step.id, attempt + 1)

        execution.duration_ms = int((time.perf_counter() - started) * 1000)
        if execution.status != "succeeded":
            execution.status = "failed"

        if execution.status == "succeeded" and reversible:
            await undo_engine.record(
                run_id=run_id, approval_id=approval_id, tool=step.tool or "",
                params=step.params, before=before
            )

        await audit_log.record(
            action="tool.executed",
            outcome="success" if execution.status == "succeeded" else "failed",
            actor="brain",
            run_id=run_id,
            tool=step.tool,
            params=step.params,
            permission_level=execution.permission_level,
            approval_id=approval_id,
            error=execution.error,
        )
        if execution.status == "succeeded" and not (execution.verification and execution.verification.independent):
            await audit_log.record(
                action="tool.unverified", outcome="unverified", actor="brain", run_id=run_id, tool=step.tool,
                params=step.params, permission_level=execution.permission_level,
                error=execution.verification.reason if execution.verification else "no verification",
            )
        return execution

    @staticmethod
    def _check_paths(params: dict[str, Any]) -> None:
        for key, value in params.items():
            if key in PATH_PARAM_KEYS and isinstance(value, str) and value.strip():
                guard(value, root=workspace_root())

    @staticmethod
    async def _invoke(tool: Any, params: dict[str, Any]) -> ToolOutcome:
        try:
            result = await asyncio.wait_for(tool.execute(**params), timeout=max(1.0, float(tool.timeout)))
        except asyncio.TimeoutError:
            return ToolOutcome(success=False, error=f"{tool.name} timed out", metadata={"timeout": True})
        except Exception as exc:  # a tool must never be able to take the brain down
            logger.exception("tool %s crashed", tool.name)
            return ToolOutcome(success=False, error=f"{type(exc).__name__}: {exc}"[:300])
        return ToolOutcome(
            success=bool(result.success),
            data=dict(result.data or {}),
            error=result.error,
            duration_ms=int(result.duration_ms or 0),
            metadata={"tool_claimed": bool(result.verified), "tool_name": tool.name},
        )


def _summary(step: PlanStep) -> str:
    """The sentence the user actually reads before approving."""

    params = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(step.params.items())[:5])
    return f"{step.description or step.tool} -> {step.tool}({params})" if params else (
        f"{step.description or step.tool} -> {step.tool}"
    )


execution_engine = ExecutionEngine()
