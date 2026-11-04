"""Typed contracts exchanged between the brain's engines.

Engines talk through these models (and the event bus), never by importing each
other's internals.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskType = Literal[
    "chat", "research", "coding", "document", "file_task",
    "project_scaffold", "memory_request", "home_control", "device_control",
    "unknown",
]
Complexity = Literal["simple", "moderate", "complex"]
RiskLevel = Literal["none", "low", "medium", "high"]
PrivacyLevel = Literal["local_only", "allow_external_with_consent", "allow_external"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class TaskUnderstanding(BaseModel):
    task_type: TaskType = "chat"
    complexity: Complexity = "simple"
    needs_tools: list[str] = Field(default_factory=list)
    needs_documents: bool = False
    needs_memory: bool = True
    needs_vision: bool = False
    risk_level: RiskLevel = "low"
    ambiguities: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    language: str = "english"
    summary: str = ""

    @property
    def needs_planning(self) -> bool:
        return self.complexity in ("moderate", "complex")


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("step"))
    description: str
    tool: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    required_permission: int = 1
    completion_criteria: str = ""
    verification: dict[str, Any] = Field(default_factory=dict)
    max_retries: int = 1
    status: Literal["pending", "running", "done", "failed", "skipped", "awaiting_approval"] = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    rationale: str = ""
    created_at: str = Field(default_factory=_utcnow)

    @property
    def is_single_step(self) -> bool:
        return len(self.steps) <= 1

    def step_by_id(self, step_id: str) -> PlanStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def ready_steps(self, done_ids: set[str]) -> list[PlanStep]:
        return [
            step
            for step in self.steps
            if step.status == "pending" and all(dep in done_ids for dep in step.depends_on)
        ]


class RoutingDecision(BaseModel):
    model: str
    provider: str
    reason: str
    scores: dict[str, float] = Field(default_factory=dict)
    alternatives: list[str] = Field(default_factory=list)
    fallback_chain: list[tuple[str, str]] = Field(default_factory=list)
    privacy_level: PrivacyLevel = "local_only"
    data_leaves_device: bool = False
    estimated_cost_usd: float = 0.0
    degraded: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["fallback_chain"] = [list(pair) for pair in self.fallback_chain]
        return payload


class ToolAction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("act"))
    run_id: str | None = None
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    permission_level: int = 1
    description: str = ""
    param_hash: str = ""
    created_at: str = Field(default_factory=_utcnow)


class ToolOutcome(BaseModel):
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    verified: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""
    independent: bool = False

    @property
    def failed_checks(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if not c.get("passed")]


class StageTiming(BaseModel):
    stage: str
    started_at: str = Field(default_factory=_utcnow)
    finished_at: str | None = None
    status: Literal["running", "completed", "failed", "skipped"] = "running"
    detail: dict[str, Any] = Field(default_factory=dict)


class ContextTraceItem(BaseModel):
    kind: Literal["system", "task_instructions", "memory", "history", "documents", "tool_results"]
    label: str
    tokens_est: int
    included: bool
    reason: str = ""


class ContextBundle(BaseModel):
    system: str = ""
    instructions: str = ""
    memory: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[ContextTraceItem] = Field(default_factory=list)
    tokens_est: int = 0
    budget: int = 6000


class AssistantReply(BaseModel):
    text: str
    run_id: str
    model: str = ""
    provider: str
    tool_actions: list[dict[str, Any]] = Field(default_factory=list)
    verification: VerificationResult | None = None
    routing: RoutingDecision | None = None
    memory_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    blockers: list[str] = Field(default_factory=list)
