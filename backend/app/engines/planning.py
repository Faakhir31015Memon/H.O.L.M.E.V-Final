"""Planning engine: decompose a goal into an ordered, permission-tagged plan.

Trust rule baked in here: a plan step's permission level always comes from the
registered tool, never from whatever the model claimed. The model proposes; the
catalog disposes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import settings
from app.engines.types import Plan, PlanStep, RoutingDecision, TaskUnderstanding
from app.engines.verification import PATH_KEYS
from app.providers.base import ChatMessage, RunControl, ToolSpec
from app.providers.router import NoModelAvailable, RouteRequest, ai_router

logger = logging.getLogger("holmev.engines.planning")


@dataclass
class PlanOutcome:
    plan: Plan
    routing: RoutingDecision | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    rejected_steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def needs_approval(self) -> bool:
        return any(step.required_permission >= 2 for step in self.plan.steps)


class PlanningEngine:
    def direct_answer_plan(self, goal: str, understanding: TaskUnderstanding) -> Plan:
        return Plan(
            goal=goal,
            rationale="simple request - answering directly, no tool steps needed",
            steps=[],
        ) if understanding.risk_level == "none" and not understanding.needs_tools else Plan(
            goal=goal,
            rationale="single-step request",
            steps=[
                PlanStep(
                    description=understanding.summary or goal,
                    tool=understanding.needs_tools[0] if understanding.needs_tools else None,
                    required_permission=1,
                    completion_criteria="tool returned success and the result was verified",
                )
            ],
        )

    def _build_prompt(
        self, goal: str, understanding: TaskUnderstanding, catalog: dict[str, ToolSpec],
        context: dict[str, Any] | None, previous_error: str | None,
    ) -> str:
        tool_lines = [
            f"- {spec.name}: {spec.description} | params={json.dumps(spec.parameters.get('properties', {}))[:400]}"
            for spec in catalog.values()
        ]
        repair = (
            f"\nYour previous plan was rejected: {previous_error}\nProduce a corrected plan.\n"
            if previous_error
            else ""
        )
        return (
            "Break this goal into the smallest correct ordered plan. Reply with ONE JSON object only.\n\n"
            '{"goal": "...", "rationale": "...", "steps": [{"id": "s1", "description": "...", '
            '"tool": "exact tool name or null", "params": {...}, "depends_on": ["s0"], '
            '"completion_criteria": "how to prove it worked"}]}\n\n'
            "Rules:\n"
            "- Use only tools from the list. Never invent a tool name.\n"
            "- Keep it under 12 steps. Prefer fewer.\n"
            "- depends_on references earlier step ids only; no cycles.\n"
            "- completion_criteria must be checkable from the tool result.\n"
            "- A step that deletes, sends, calls, or publishes must be its own step so it can be approved alone.\n\n"
            f"Tools:\n{chr(10).join(tool_lines)}\n\n"
            f"Context: {json.dumps(context or {}, default=str)[:900]}\n"
            f"Reading of the request: type={understanding.task_type} complexity={understanding.complexity} "
            f"risk={understanding.risk_level}\n"
            f"{repair}\n"
            f"Goal: {goal}\n"
        )

    def validate_payload(
        self, payload: dict[str, Any], catalog: dict[str, ToolSpec], goal: str
    ) -> tuple[Plan | None, list[str], list[dict[str, Any]]]:
        errors: list[str] = []
        rejected: list[dict[str, Any]] = []
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            return None, ["plan must contain a 'steps' array"], rejected
        if not raw_steps:
            return None, ["plan contains no steps"], rejected
        if len(raw_steps) > settings.MAX_STEPS_PER_RUN:
            errors.append(f"plan has {len(raw_steps)} steps; the limit is {settings.MAX_STEPS_PER_RUN}")
            raw_steps = raw_steps[: settings.MAX_STEPS_PER_RUN]

        steps: list[PlanStep] = []
        seen_ids: set[str] = set()
        id_map: dict[str, str] = {}

        for index, entry in enumerate(raw_steps):
            if not isinstance(entry, dict):
                errors.append(f"step {index} is not an object")
                continue
            supplied_id = str(entry.get("id") or f"s{index + 1}")
            canonical_id = f"s{index + 1}"
            id_map[supplied_id] = canonical_id

            tool = entry.get("tool")
            tool_name: str | None = None
            if tool is not None and str(tool).strip() and str(tool).lower() not in ("null", "none"):
                tool_name = str(tool).strip()
                if tool_name not in catalog:
                    rejected.append({"step": supplied_id, "tool": tool_name, "reason": "unknown tool"})
                    errors.append(f"step {supplied_id} names unknown tool '{tool_name}'")
                    continue

            params = entry.get("params")
            if params is not None and not isinstance(params, dict):
                errors.append(f"step {supplied_id} params must be an object")
                params = {}

            steps.append(
                PlanStep(
                    id=canonical_id,
                    description=str(entry.get("description") or f"step {index + 1}")[:500],
                    tool=tool_name,
                    params=params or {},
                    depends_on=[str(dep) for dep in (entry.get("depends_on") or []) if isinstance(dep, (str, int))],
                    required_permission=catalog[tool_name].permission_level if tool_name else 0,
                    completion_criteria=str(entry.get("completion_criteria") or "")[:300],
                    verification=self._infer_verification(tool_name, catalog, params or {}),
                )
            )
            if canonical_id in seen_ids:
                errors.append(f"duplicate step id {canonical_id}")
            seen_ids.add(canonical_id)

        # Rewrite declared dependencies onto canonical ids, then drop self/cyclic links.
        for step in steps:
            step.depends_on = [
                id_map.get(dep, dep) for dep in step.depends_on if id_map.get(dep, dep) != step.id
            ]
        known = {step.id for step in steps}
        for step in steps:
            step.depends_on = [dep for dep in step.depends_on if dep in known]

        cycle = self._find_cycle(steps)
        if cycle:
            errors.append(f"plan contains a dependency cycle: {' -> '.join(cycle)}")

        if not steps:
            return None, errors or ["plan produced no usable steps"], rejected
        if cycle:
            return None, errors, rejected

        return (
            Plan(
                goal=str(payload.get("goal") or goal)[:500],
                rationale=str(payload.get("rationale") or "")[:400],
                steps=steps,
            ),
            errors,
            rejected,
        )

    @staticmethod
    def _infer_verification(
        tool_name: str | None, catalog: dict[str, ToolSpec], params: dict[str, Any]
    ) -> dict[str, Any]:
        """Pick the strongest check the tool's own input schema allows.

        Filesystem proof is only demanded of tools that take a path; a device
        control is checked by reading its state back from the registry.
        """

        if not tool_name:
            return {"type": "none"}
        spec = catalog[tool_name]
        description = (spec.description or "").lower()
        properties = spec.parameters.get("properties") or {}
        param_names = {str(key).lower() for key in properties}
        path_key = next((key for key in PATH_KEYS if key in param_names), None)

        if path_key and ("delete" in description or "remove" in description):
            return {"type": "path_absent"}
        if path_key and ("create" in description or "write" in description or "folder" in description
                         or "scaffold" in description):
            return {"type": "path_exists"}
        if "power" in param_names and isinstance(params.get("power"), bool):
            expect: dict[str, Any] = {"power": params["power"]}
            if params.get("speed") is not None:
                expect["speed"] = params["speed"]
            return {"type": "state_matches", "observe": "device", "expect": expect}
        if "read" in description or "list" in description or "search" in description:
            return {"type": "non_empty"}
        return {"type": "tool_success"}

    @staticmethod
    def _find_cycle(steps: list[PlanStep]) -> list[str] | None:
        graph = {step.id: step.depends_on for step in steps}
        state: dict[str, str] = {}

        def visit(node: str, path: list[str]) -> list[str] | None:
            if state.get(node) == "visiting":
                return [*path, node]
            if state.get(node) == "done":
                return None
            state[node] = "visiting"
            for dep in graph.get(node, []):
                found = visit(dep, [*path, node])
                if found:
                    return found
            state[node] = "done"
            return None

        for step_id in graph:
            found = visit(step_id, [])
            if found:
                return found
        return None

    async def build(
        self,
        goal: str,
        understanding: TaskUnderstanding,
        catalog: dict[str, ToolSpec],
        *,
        context: dict[str, Any] | None = None,
        control: RunControl | None = None,
        system: str | None = None,
    ) -> PlanOutcome:
        if understanding.complexity == "simple" and not understanding.needs_tools:
            return PlanOutcome(plan=self.direct_answer_plan(goal, understanding), notes=["fast path: no planning"])

        messages = [ChatMessage(role="user", content="")]
        last_error: str | None = None
        outcome: PlanOutcome | None = None

        for attempt in range(settings.MAX_PLAN_JSON_REPAIRS + 1):
            messages[0].content = self._build_prompt(goal, understanding, catalog, context, last_error)
            try:
                payload, run, error = await ai_router.run_json(
                    RouteRequest(
                        required_capabilities={"reasoning", "tool_use"},
                        complexity=understanding.complexity,
                        est_input_tokens=len(messages[0].content) // 4,
                        task_type=understanding.task_type,
                    ),
                    messages,
                    system,
                    max_tokens=1200,
                    temperature=0.0 if attempt else 0.1,
                    control=control,
                    metadata={"stage": "planning", "attempt": attempt},
                )
            except NoModelAvailable as exc:
                return PlanOutcome(
                    plan=self.direct_answer_plan(goal, understanding),
                    routing=exc.decision,
                    degraded=True,
                    notes=[exc.decision.reason],
                )

            if error or payload is None:
                last_error = error or "empty plan payload"
                outcome = PlanOutcome(
                    plan=self.direct_answer_plan(goal, understanding),
                    routing=run.decision if run else None,
                    degraded=True,
                    notes=[f"plan attempt {attempt + 1} failed: {last_error}"],
                )
                continue

            plan, errors, rejected = self.validate_payload(payload, catalog, goal)
            if plan is None or not plan.steps:
                last_error = "; ".join(errors) or "plan produced no usable steps"
                outcome = PlanOutcome(
                    plan=self.direct_answer_plan(goal, understanding),
                    routing=run.decision if run else None,
                    degraded=True,
                    notes=[f"plan rejected: {last_error}"],
                    rejected_steps=rejected,
                )
                continue

            notes: list[str] = []
            if rejected:
                notes.append(f"dropped {len(rejected)} step(s) naming tools that do not exist")
            if errors:
                notes.append("step warnings: " + "; ".join(errors[:3]))
            if run is not None:
                notes.append(f"plan built by {run.decision.provider}:{run.decision.model}")
            return PlanOutcome(
                plan=plan,
                routing=run.decision if run else None,
                degraded=bool(run and run.decision.degraded),
                notes=notes,
                rejected_steps=rejected,
            )

        if outcome is not None:
            outcome.notes.append("falling back to a single-step plan")
            return outcome
        return PlanOutcome(
            plan=self.direct_answer_plan(goal, understanding),
            degraded=True,
            notes=["planner produced no plan"],
        )


planning_engine = PlanningEngine()
