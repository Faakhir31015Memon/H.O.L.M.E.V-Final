"""The orchestrator: one run, one state machine, one honest record of what happened.

    CREATED -> UNDERSTANDING -> PLANNING -> ROUTING -> EXECUTING
            -> (AWAITING_APPROVAL) -> VERIFYING -> REPORTING -> COMPLETED

Every transition is timed, persisted and emitted. A run that stops at
AWAITING_APPROVAL can only continue when the user grants the exact action, and
`resume()` re-runs the plan stored server-side rather than trusting anything the
client claims about what it approved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config.settings import settings
from app.context.engine import context_store
from app.database.models import Approval, RunStage, TaskRun
from app.database.session import session_scope
from app.engines.execution import ExecutionReport, execution_engine
from app.engines.memory import memory_engine
from app.engines.planning import planning_engine
from app.engines.response import response_engine
from app.engines.safety import safety_engine
from app.engines.types import (
    AssistantReply,
    ContextBundle,
    ContextTraceItem,
    Plan,
    RoutingDecision,
    TaskUnderstanding,
    VerificationResult,
    new_id,
)
from app.engines.understanding import understanding_engine
from app.engines.verification import verification_engine
from app.events.bus import EventKind, event_bus
from app.prompts import system_prompt
from app.providers.base import ChatMessage, RunControl
from app.providers.router import RouteRequest, ai_router
from app.security.approvals import approval_service
from app.security.stop import emergency_stop
from app.tools.registry import tool_registry

logger = logging.getLogger("holmev.orchestrator")


@dataclass
class StageRecord:
    stage: str
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    duration_ms: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def finish(self, status: str, detail: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc)
        self.status = status
        self.finished_at = now.isoformat()
        self.detail = detail or {}
        started = datetime.fromisoformat(self.started_at)
        self.duration_ms = int((now - started).total_seconds() * 1000)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
        }


@dataclass
class RunOutcome:
    run_id: str
    session_id: str
    status: str
    reply: AssistantReply
    stages: list[StageRecord] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    understanding: TaskUnderstanding | None = None
    plan: Plan | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "spoken_response": self.reply.text,
            "reply": self.reply.model_dump(),
            "stages": [stage.as_dict() for stage in self.stages],
            "pending_approvals": self.pending_approvals,
            "understanding": self.understanding.model_dump() if self.understanding else None,
            "plan": self.plan.model_dump() if self.plan else None,
            "degraded": self.reply.degraded,
            "verified": bool(self.reply.verification and self.reply.verification.verified),
        }


class Orchestrator:
    def __init__(self) -> None:
        self._controls: dict[str, RunControl] = {}

    # ------------------------------------------------------------------ one full pass

    async def run(
        self,
        query: str,
        *,
        session_id: str = "default_session",
        emotion: str | None = None,
        documents: list[dict[str, Any]] | None = None,
    ) -> RunOutcome:
        """One request in, one honest outcome out - even when the machinery breaks."""

        clean_query = (query or "").strip()[:4000]
        run_id = new_id("run")
        control = RunControl()
        self._start_run(run_id, control)
        stages: list[StageRecord] = []
        await self._save_run(run_id, session_id=session_id, user_query=clean_query, status="CREATED",
                             stage="CREATED")
        await event_bus.emit_kind(
            EventKind.RUN_STARTED, session_id=session_id, correlation_id=run_id,
            payload={"run_id": run_id, "query": clean_query[:300], "emotion": emotion},
        )
        try:
            return await self._execute_run(run_id, control, stages, clean_query, session_id, emotion, documents)
        except Exception as exc:
            logger.exception("run %s stopped with an internal error", run_id)
            detail = f"{type(exc).__name__}: {exc}"[:400]
            await self._save_run(run_id, status="FAILED", stage="FAILED", error=detail, finished=True)
            await event_bus.emit_kind(
                EventKind.RUN_FAILED, session_id=session_id, correlation_id=run_id,
                payload={"run_id": run_id, "error": detail},
            )
            self._release(run_id)
            return self._outcome(
                run_id, session_id, "FAILED",
                AssistantReply(
                    text=(
                        "I stopped before finishing because of an internal error "
                        f"({detail}). Nothing after that point was attempted."
                    ),
                    run_id=run_id,
                    provider="none",
                    degraded=True,
                    blockers=[detail],
                ),
                stages,
                None,
                None,
            )

    async def _execute_run(
        self,
        run_id: str,
        control: RunControl,
        stages: list[StageRecord],
        clean_query: str,
        session_id: str,
        emotion: str | None,
        documents: list[dict[str, Any]] | None,
    ) -> RunOutcome:
        if not clean_query:
            return await self._finish(
                run_id, session_id, stages,
                _empty_input_reply(run_id), status="COMPLETED", control=control,
            )

        context_store.get(session_id).remember_turn(clean_query, "user")
        catalog = tool_registry.describe_all()

        # ---------------------------------------------------------- UNDERSTANDING
        bundle = await self._context_bundle(clean_query, session_id, documents)
        view = self._view(bundle, session_id)
        stage = self._stage(stages, "UNDERSTANDING")
        # The JSON stages get their schema-only prompt: their output contract is
        # already fully specified in the user turn, so a persona adds nothing.
        reading = await understanding_engine.analyze(
            clean_query, tool_names=sorted(catalog), context=view, control=control
        )
        understanding = reading.understanding
        await self._end_stage(
            run_id, stage, "degraded" if reading.degraded else "completed",
            {
                "task_type": understanding.task_type,
                "complexity": understanding.complexity,
                "risk": understanding.risk_level,
                "language": understanding.language,
                "needs_tools": understanding.needs_tools,
                "confidence": understanding.confidence,
                "notes": reading.notes[:3],
            },
            event=EventKind.UNDERSTOOD,
            session_id=session_id,
        )

        # -------------------------------------------------------------- PLANNING
        stage = self._stage(stages, "PLANNING")
        planned = await planning_engine.build(
            clean_query, understanding, catalog, context=view, control=control
        )
        plan = planned.plan
        await self._end_stage(
            run_id, stage, "degraded" if planned.degraded else "completed",
            {
                "steps": [step.id for step in plan.steps],
                "rationale": plan.rationale[:200],
                "needs_approval": planned.needs_approval,
                "notes": planned.notes[:3],
                "rejected_steps": planned.rejected_steps[:3],
            },
            event=EventKind.PLAN_READY,
            session_id=session_id,
        )
        routing: RoutingDecision | None = planned.routing
        await self._save_run(
            run_id, session_id=session_id, user_query=clean_query, status="PLANNING", stage="PLANNING",
            understanding=understanding.model_dump(), plan=plan.model_dump(),
            routing=routing.as_dict() if routing else None,
            context_trace=[item.model_dump() for item in bundle.trace],
            degraded=planned.degraded, total_steps=len(plan.steps),
        )

        # -------------------------------------------------------------- EXECUTING
        report = ExecutionReport()
        if plan.steps:
            stage = self._stage(stages, "EXECUTING")
            report = await execution_engine.run_plan(
                plan, run_id=run_id, session_id=session_id, control=control
            )
            await self._end_stage(
                run_id, stage,
                "awaiting_approval" if report.pending_approvals else (
                    "cancelled" if report.cancelled else "completed"
                ),
                {
                    "executions": [execution.as_dict() for execution in report.executions],
                    "awaiting": [item["approval_id"] for item in report.pending_approvals],
                    "stop_reason": report.stop_reason,
                },
                event=EventKind.STEP_FINISHED,
                session_id=session_id,
            )
            self._apply_effects(session_id, report)

        # ------------------------------------------------------ AWAITING_APPROVAL
        if report.pending_approvals:
            reply = self._approval_request_reply(run_id, report.pending_approvals, routing)
            await self._save_run(
                run_id, status="AWAITING_APPROVAL", stage="AWAITING_APPROVAL", reply=reply.text,
                blocked=True, degraded=planned.degraded,
            )
            for item in report.pending_approvals:
                await event_bus.emit_kind(
                    EventKind.APPROVAL_REQUESTED, session_id=session_id, correlation_id=run_id, payload=item
                )
            self._release(run_id)
            return self._outcome(run_id, session_id, "AWAITING_APPROVAL", reply, stages, plan, understanding,
                                 pending=report.pending_approvals)

        # -------------------------------------------------------------- VERIFYING
        verifications = report.verifications()
        stage = self._stage(stages, "VERIFYING")
        worst = verification_engine.least_verified(verifications)
        all_verified = bool(verifications) and all(r.verified for r in verifications.values())
        await self._end_stage(
            run_id, stage,
            "completed" if (all_verified or not verifications) else "failed",
            {
                "verified": all_verified,
                "independently_verified": bool(verifications) and all(
                    r.independent for r in verifications.values()
                ),
                "reason": worst.reason if worst else "nothing to verify",
            },
            event=EventKind.STAGE_FINISHED,
            session_id=session_id,
        )

        # -------------------------------------------------------------- REPORTING
        stage = self._stage(stages, "REPORTING")
        draft = await response_engine.compose(
            goal=clean_query,
            understanding=understanding,
            plan=plan,
            outcomes=report.by_step(),
            verifications=verifications,
            context=view,
            emotion=emotion,
            control=control,
            system=system_prompt(),
            documents=bundle.documents,
        )
        await self._end_stage(
            run_id, stage, "degraded" if draft.degraded else "completed", {"notes": draft.notes[:3]},
            event=EventKind.REPLY_DELTA, session_id=session_id,
        )

        memory_suggestions = await self._maybe_remember(
            clean_query, understanding, run_id, session_id, control
        )
        reply = AssistantReply(
            text=draft.text,
            run_id=run_id,
            model=draft.routing.model if draft.routing else "",
            provider=draft.routing.provider if draft.routing else "none",
            tool_actions=[execution.as_dict() for execution in report.executions],
            verification=_merge_verifications(verifications),
            routing=draft.routing or routing,
            memory_suggestions=memory_suggestions,
            degraded=draft.degraded or planned.degraded or reading.degraded or report.cancelled,
            blockers=[note for note in draft.notes if note][:4],
        )
        status = "CANCELLED" if control.cancelled else "COMPLETED"
        return await self._finish(
            run_id, session_id, stages, reply, status=status, control=control, plan=plan,
            understanding=understanding, degraded=reply.degraded,
            verified=bool(reply.verification and reply.verification.verified),
        )

    # ------------------------------------------------------------------ resume after approval

    async def resume(self, run_id: str) -> RunOutcome:
        """Continue a run that stopped for approval, using only what this device recorded.

        The decisions are read from the approvals table scoped to this run, so a
        client cannot replay a grant belonging to another run or assert an
        approval that was never actually given.
        """

        async with session_scope() as db:
            row = await db.get(TaskRun, run_id)
            if row is None:
                raise KeyError(f"No run with id '{run_id}'.")
            session_id = row.session_id
            query = row.user_query
            stored_plan = dict(row.plan or {})
            understanding = TaskUnderstanding.model_validate(row.understanding or {})
            decisions = (
                await db.execute(select(Approval).where(Approval.run_id == run_id))
            ).scalars().all()

        if not stored_plan.get("steps"):
            raise ValueError("that run has no steps left to resume")

        grants, refusals = _split_decisions(list(decisions))
        plan = Plan.model_validate(stored_plan)
        control = RunControl()
        self._start_run(run_id, control)
        stages: list[StageRecord] = []
        await event_bus.emit_kind(
            EventKind.RUN_STARTED, session_id=session_id, correlation_id=run_id,
            payload={"run_id": run_id, "resumed": True, "granted": len(grants), "refused": len(refusals)},
        )

        stage = self._stage(stages, "EXECUTING")
        report = await execution_engine.run_plan(
            plan, run_id=run_id, session_id=session_id, control=control, grants=grants, refusals=refusals
        )
        await self._end_stage(
            run_id, stage,
            "awaiting_approval" if report.pending_approvals else (
                "cancelled" if report.cancelled else "completed"
            ),
            {"executions": [execution.as_dict() for execution in report.executions]},
            event=EventKind.STEP_FINISHED, session_id=session_id,
        )
        self._apply_effects(session_id, report)

        verifications = report.verifications()
        draft = await response_engine.compose(
            goal=query, understanding=understanding, plan=plan, outcomes=report.by_step(),
            verifications=verifications, context=self._view(None, session_id), control=control,
            system=system_prompt(),
        )
        reply = AssistantReply(
            text=draft.text,
            run_id=run_id,
            model=draft.routing.model if draft.routing else "",
            provider=draft.routing.provider if draft.routing else "none",
            tool_actions=[execution.as_dict() for execution in report.executions],
            verification=_merge_verifications(verifications),
            routing=draft.routing,
            degraded=draft.degraded or report.cancelled,
            blockers=[note for note in draft.notes if note][:4],
        )

        if report.pending_approvals:
            await self._save_run(
                run_id, status="AWAITING_APPROVAL", stage="AWAITING_APPROVAL", reply=reply.text, blocked=True
            )
            for item in report.pending_approvals:
                await event_bus.emit_kind(
                    EventKind.APPROVAL_REQUESTED, session_id=session_id, correlation_id=run_id, payload=item
                )
            self._release(run_id)
            return self._outcome(
                run_id, session_id, "AWAITING_APPROVAL", reply, stages, plan, understanding,
                pending=report.pending_approvals,
            )

        status = "CANCELLED" if control.cancelled else "COMPLETED"
        return await self._finish(
            run_id, session_id, stages, reply, status=status, control=control, plan=plan,
            understanding=understanding, degraded=reply.degraded,
            verified=bool(reply.verification and reply.verification.verified),
        )

    async def cancel(self, run_id: str) -> bool:
        control = self._controls.get(run_id)
        if control is None:
            return False
        control.cancel()
        await approval_service.cancel_pending_for_run(run_id)
        await self._save_run(run_id, status="CANCELLED", stage="CANCELLED", finished=True)
        await event_bus.emit_kind(EventKind.RUN_CANCELLED, correlation_id=run_id, payload={"run_id": run_id})
        self._release(run_id)
        return True

    # ------------------------------------------------------------------ internals

    def _start_run(self, run_id: str, control: RunControl) -> None:
        self._controls[run_id] = control
        emergency_stop.register_control(run_id, control)

    def _release(self, run_id: str) -> None:
        emergency_stop.release_control(run_id)
        self._controls.pop(run_id, None)

    @staticmethod
    def _stage(stages: list[StageRecord], name: str) -> StageRecord:
        record = StageRecord(stage=name)
        stages.append(record)
        return record

    async def _end_stage(
        self, run_id: str, stage: StageRecord, status: str, detail: dict[str, Any], *,
        event: str, session_id: str
    ) -> None:
        stage.finish(status, detail)
        async with session_scope() as db:
            db.add(
                RunStage(
                    run_id=run_id,
                    stage=stage.stage,
                    status=stage.status,
                    duration_ms=stage.duration_ms,
                    detail=stage.detail,
                    started_at=datetime.fromisoformat(stage.started_at),
                    finished_at=datetime.fromisoformat(stage.finished_at) if stage.finished_at else None,
                )
            )
        await event_bus.emit_kind(
            event, session_id=session_id, correlation_id=run_id, payload={"stage": stage.as_dict()}
        )

    async def _finish(
        self, run_id: str, session_id: str, stages: list[StageRecord], reply: AssistantReply, *,
        status: str, control: RunControl, plan: Plan | None = None,
        understanding: TaskUnderstanding | None = None, degraded: bool = False, verified: bool = False
    ) -> RunOutcome:
        context_store.get(session_id).remember_turn(reply.text, "assistant")
        await self._save_run(
            run_id, session_id=session_id, status=status, stage="COMPLETED", reply=reply.text,
            model=reply.model, provider=reply.provider, degraded=degraded, verified=verified, finished=True,
        )
        await event_bus.emit_kind(
            EventKind.RUN_CANCELLED if status == "CANCELLED" else EventKind.RUN_COMPLETED,
            session_id=session_id, correlation_id=run_id, payload=reply.model_dump(),
        )
        self._release(run_id)
        return self._outcome(run_id, session_id, status, reply, stages, plan, understanding)

    @staticmethod
    def _outcome(
        run_id: str, session_id: str, status: str, reply: AssistantReply, stages: list[StageRecord],
        plan: Plan | None, understanding: TaskUnderstanding | None,
        pending: list[dict[str, Any]] | None = None
    ) -> RunOutcome:
        return RunOutcome(
            run_id=run_id, session_id=session_id, status=status, reply=reply, stages=stages,
            pending_approvals=pending or [], understanding=understanding, plan=plan,
        )

    async def _context_bundle(
        self, query: str, session_id: str, documents: list[dict[str, Any]] | None
    ) -> ContextBundle:
        """Assemble prompt context, wrapping every untrusted part as data."""

        memories, trace = await memory_engine.context_pack(query, session=session_id)
        snapshot = context_store.get(session_id).snapshot()
        bundle = ContextBundle(
            system=system_prompt(),
            instructions=query,
            memory=memories,
            history=snapshot.get("recent_messages", [])[-settings.CONVERSATION_HISTORY_TURNS :],
            budget=settings.CONTEXT_TOKEN_BUDGET,
        )

        for document in documents or []:
            name = str(document.get("name") or "document")
            text = str(document.get("text") or "")
            report = safety_engine.scan_untrusted_text(text, source=name)
            if report.blocked:
                trace.append(
                    ContextTraceItem(
                        kind="documents", label=name, tokens_est=0, included=False,
                        reason="instruction-like content inside the document was blocked",
                    )
                )
                bundle.documents.append(
                    {"name": name, "blocked": True, "findings": [f.as_dict() for f in report.findings]}
                )
                continue
            wrapped = safety_engine.wrap_untrusted(text, source=name)
            bundle.documents.append({"name": name, "content": wrapped[:4000]})
            trace.append(
                ContextTraceItem(
                    kind="documents", label=name, tokens_est=max(1, len(wrapped) // 4),
                    included=True, reason="wrapped as untrusted data",
                )
            )

        bundle.trace = trace
        bundle.tokens_est = sum(item.tokens_est for item in trace) + len(bundle.system) // 4
        return bundle

    @staticmethod
    def _view(bundle: ContextBundle | None, session_id: str) -> dict[str, Any]:
        snapshot = context_store.get(session_id).snapshot()
        return {
            "memory": [f"{item['key']}={item['value'][:120]}" for item in (bundle.memory if bundle else [])][:8],
            "history": (bundle.history if bundle else [])[-4:],
            "documents": [item.get("content", "[blocked]")[:400] for item in (bundle.documents if bundle else [])][:3],
            "session": {
                key: snapshot.get(key)
                for key in ("active_room", "active_device", "active_3d_object", "active_circuit_id", "last_tool")
            },
        }

    @staticmethod
    def _apply_effects(session_id: str, report: ExecutionReport) -> None:
        """Context moves only from steps that really ran and really verified."""

        session = context_store.get(session_id)
        for execution in report.executions:
            if execution.status != "succeeded" or not execution.tool:
                continue
            data = execution.outcome.data if execution.outcome else {}
            session.apply_tool_effect(execution.tool, execution.params, data)

    async def _maybe_remember(
        self, query: str, understanding: TaskUnderstanding, run_id: str, session_id: str,
        control: RunControl
    ) -> list[dict[str, Any]]:
        if understanding.task_type != "memory_request" and not _remember_hint(query):
            return []

        suggestions: list[dict[str, Any]] = []
        for proposal in await self._extract_memories(query, control):
            try:
                result = await memory_engine.propose(
                    key=proposal["key"], value=proposal["value"], layer=proposal.get("layer", "semantic"),
                    confidence=proposal.get("confidence", 0.5), source_run_id=run_id, session=session_id,
                )
            except Exception as exc:
                logger.info("memory proposal refused: %s", exc)
                continue
            if not result.stored:
                suggestions.append({"stored": False, "reason": result.blocked_reason, **proposal})
                continue
            suggestions.append(result.as_dict())
            await event_bus.emit_kind(
                EventKind.MEMORY_PROPOSED, session_id=session_id, correlation_id=run_id,
                payload=result.as_dict(),
            )
        return suggestions

    async def _extract_memories(self, query: str, control: RunControl) -> list[dict[str, Any]]:
        prompt = (
            "Extract what the user wants remembered as durable facts.\n"
            'Reply with ONE JSON object: {"memories": [{"key": "snake_case_name", "value": "short fact", '
            '"layer": "semantic|procedural|episodic", "confidence": 0.0-1.0}]}\n'
            "Rules: keep only what stays true for months, never invent details, return an empty list when "
            "there is nothing worth remembering, and never extract passwords, ID numbers or health details.\n\n"
            f"Request: {query}\n"
        )
        try:
            payload, _run, error = await ai_router.run_json(
                RouteRequest(
                    required_capabilities={"structured_output"}, complexity="simple",
                    est_input_tokens=len(prompt) // 4, task_type="memory_request",
                ),
                [ChatMessage(role="user", content=prompt)],
                system=system_prompt(),
                max_tokens=400,
                temperature=0.0,
                control=control,
                metadata={"stage": "memory_extract"},
            )
        except Exception as exc:
            logger.info("memory extraction unavailable: %s", exc)
            return [_rule_memory(query)]

        if error or not isinstance(payload, dict):
            return [_rule_memory(query)]
        raw = payload.get("memories")
        if not isinstance(raw, list):
            return []

        cleaned: list[dict[str, Any]] = []
        for item in raw[:5]:
            if isinstance(item, dict) and item.get("key") and item.get("value"):
                cleaned.append(
                    {
                        "key": str(item["key"])[:200],
                        "value": str(item["value"])[:2000],
                        "layer": item["layer"] if item.get("layer") in ("semantic", "procedural", "episodic")
                        else "semantic",
                        "confidence": float(item.get("confidence") or 0.6),
                    }
                )
        return cleaned

    @staticmethod
    def _approval_request_reply(
        run_id: str, pending: list[dict[str, Any]], routing: RoutingDecision | None
    ) -> AssistantReply:
        lines = [
            f"  {index}. {item['tool']} - {_preview_params(item['params'])} [permission L{item['permission_level']}]"
            for index, item in enumerate(pending, start=1)
        ]
        text = (
            f"{len(pending)} action(s) need your approval before I run them, because they touch your "
            "device, your data, or the outside world:\n" + "\n".join(lines) +
            "\n\nNothing has been done yet. Approve the ones you want and I will continue; each approval "
            "covers exactly those parameters and expires on its own."
        )
        return AssistantReply(
            text=text,
            run_id=run_id,
            model=routing.model if routing else "",
            provider=routing.provider if routing else "none",
            blockers=[f"awaiting approval for {item['tool']}" for item in pending],
        )

    async def _save_run(
        self,
        run_id: str,
        *,
        session_id: str | None = None,
        user_query: str | None = None,
        status: str,
        stage: str,
        understanding: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        routing: dict[str, Any] | None = None,
        context_trace: list[dict[str, Any]] | None = None,
        reply: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        degraded: bool | None = None,
        verified: bool | None = None,
        blocked: bool | None = None,
        total_steps: int | None = None,
        finished: bool | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status, "stage": stage}
        optional = {
            "session_id": session_id, "user_query": user_query, "understanding": understanding, "plan": plan,
            "routing": routing, "context_trace": context_trace, "reply": reply, "model": model,
            "provider": provider, "degraded": degraded, "verified": verified, "blocked": blocked,
            "total_steps": total_steps, "error": error,
        }
        values.update({key: value for key, value in optional.items() if value is not None})
        if finished:
            values["finished_at"] = datetime.now(timezone.utc)

        async with session_scope() as db:
            row = await db.get(TaskRun, run_id)
            if row is None:
                db.add(TaskRun(id=run_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    # ------------------------------------------------------------------ reading state back

    async def run_trace(self, run_id: str) -> dict[str, Any] | None:
        async with session_scope() as db:
            row = await db.get(TaskRun, run_id)
            if row is None:
                return None
            stages = (
                await db.execute(select(RunStage).where(RunStage.run_id == run_id).order_by(RunStage.started_at))
            ).scalars().all()
            return {
                "run_id": row.id,
                "session_id": row.session_id,
                "status": row.status,
                "stage": row.stage,
                "query": row.user_query,
                "reply": row.reply,
                "model": row.model,
                "provider": row.provider,
                "degraded": row.degraded,
                "verified": row.verified,
                "blocked": row.blocked,
                "error": row.error,
                "understanding": row.understanding,
                "plan": row.plan,
                "routing": row.routing,
                "context_trace": row.context_trace,
                "stages": [
                    {
                        "stage": s.stage,
                        "status": s.status,
                        "duration_ms": s.duration_ms,
                        "started_at": s.started_at.isoformat() if s.started_at else None,
                        "detail": s.detail,
                    }
                    for s in stages
                ],
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }

    async def recent_runs(self, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        stmt = select(TaskRun).order_by(TaskRun.created_at.desc()).limit(min(limit, 100))
        if session_id:
            stmt = stmt.where(TaskRun.session_id == session_id)
        async with session_scope() as db:
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    "run_id": row.id,
                    "session_id": row.session_id,
                    "status": row.status,
                    "query": (row.user_query or "")[:200],
                    "reply": (row.reply or "")[:300],
                    "degraded": row.degraded,
                    "verified": row.verified,
                    "blocked": row.blocked,
                    "total_steps": row.total_steps,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    @staticmethod
    def active_runs() -> list[str]:
        return emergency_stop.active_run_ids()


def _split_decisions(decisions: list[Approval]) -> tuple[dict[str, str], dict[str, str]]:
    """Approved hashes become one-use grants; refused ones are remembered as refusals.

    A refusal is not retried inside the same run: re-asking after a "no" is how
    an assistant becomes a nag.
    """

    grants: dict[str, str] = {}
    refusals: dict[str, str] = {}
    reasons = {
        "denied": "You denied this exact action, so it was not run. Ask again if you change your mind.",
        "cancelled": "The approval for this action was voided by the stop switch, so it was not run.",
        "expired": "This approval expired before it was answered, so nothing was run.",
    }
    for record in decisions:
        if record.status == "approved":
            grants[record.param_hash] = record.id
        elif record.status in reasons:
            refusals[record.param_hash] = reasons[record.status]
    return grants, refusals


def _empty_input_reply(run_id: str) -> AssistantReply:
    return AssistantReply(
        text="I did not receive any words to work with. Say the request again.",
        run_id=run_id,
        provider="none",
        degraded=True,
        blockers=["empty input"],
    )


def _merge_verifications(verifications: dict[str, VerificationResult]) -> VerificationResult | None:
    if not verifications:
        return None
    checks = [dict(check, step=step_id) for step_id, result in verifications.items() for check in result.checks]
    failing = next((r for r in verifications.values() if not r.verified), None)
    return VerificationResult(
        verified=all(r.verified for r in verifications.values()),
        checks=checks,
        independent=all(r.independent for r in verifications.values()),
        reason=(failing.reason if failing else "every step passed its independent check")[:300],
    )


_REMEMBER_WORDS = ("remember", "yaad rakh", "note karo", "save this", "meri pasand", "don't forget")


def _remember_hint(query: str) -> bool:
    lowered = (query or "").lower()
    return any(word in lowered for word in _REMEMBER_WORDS)


def _rule_memory(query: str) -> dict[str, Any]:
    """With no model we keep only the user's own words; the memory engine still
    screens them for protected categories before anything is written."""

    stripped = query.strip()
    lowered = stripped.lower()
    for word in _REMEMBER_WORDS:
        if word in lowered:
            stripped = lowered.replace(word, "", 1).strip(" :,.-")
            break
    return {"key": "note", "value": stripped[:500], "layer": "semantic", "confidence": 0.4}


def _preview_params(params: dict[str, Any]) -> str:
    if not params:
        return "no parameters"
    return ", ".join(f"{key}={str(value)[:70]}" for key, value in list(params.items())[:6])


orchestrator = Orchestrator()
