"""Understanding engine: turns a raw user message into a typed TaskUnderstanding.

Rules run first (they are instant and free), then a model refines the reading.
If no model is available the rule reading is still returned, clearly marked
degraded, so the pipeline never silently pretends it understood more than it did.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.engines.types import Complexity, RiskLevel, RoutingDecision, TaskType, TaskUnderstanding
from app.providers.base import ChatMessage, RunControl
from app.providers.router import NoModelAvailable, RouteRequest, ai_router

logger = logging.getLogger("holmev.engines.understanding")

_TASK_SIGNALS: dict[str, tuple[str, ...]] = {
    "coding": ("code", "bug", "function", "refactor", "debug", "script", "compile", "test", "api", "python"),
    "research": ("research", "compare", "why", "explain", "analyse", "analyze", "study", "latest", "news", "source"),
    "document": ("pdf", "document", "file", "upload", "attachment", "summarise", "summarize", "read this"),
    "file_task": ("create folder", "delete", "rename", "move file", "copy", "write to file", "folder banao",
                  "folder", "directory", "files", "move"),
    "project_scaffold": ("scaffold", "new project", "boilerplate", "template", "dashboard banao"),
    "memory_request": ("remember", "yaad rakho", "yaad rakh", "don't forget", "meri pasand"),
    "home_control": ("light", "fan", "ac", "tv", "camera", "cctv", "remote", "pankha", "batti", "door", "lock"),
    "device_control": ("open app", "launch", "shutdown", "restart", "lock screen", "screenshot", "kholo", "chalao"),
}

_RISKY_WORDS = (
    "delete", "remove", "wipe", "format", "send", "email", "call", "message", "whatsapp",
    "pay", "buy", "publish", "post", "upload", "install", "uninstall", "shutdown", "restart",
    "band karo", "bhejo", "hatao", "mitao",
)

_AMBIGUOUS = ("woh", "that one", "usay", "isay", "some", "few", "later", "thora", "whatever", "the file", "the thing")

_CONNECTORS = ("then", "after that", "plus", "and also", "phir", "iske baad", "saath mein", "because")

_ROMAN_URDU = (
    "hai", "karo", "karna", "kiya", "kya", "bhej", "dikha", "kaise", "mera", "meri", "hamara",
    "band", "chalu", "chala", "kaam", "jao", "batao", "kahin", "bohat", "thora", "kal", "aaj",
)


def detect_language(text: str) -> str:
    lowered = (text or "").lower()
    if any(ord(ch) > 0x0600 and ord(ch) < 0x0750 for ch in text or ""):
        return "urdu"
    if any(ord(ch) > 0x0900 and ord(ch) < 0x0980 for ch in text or ""):
        return "hindi"
    if any(f" {word} " in f" {lowered} " for word in _ROMAN_URDU):
        return "roman_urdu"
    return "english"


def _classify_type(text: str) -> TaskType:
    """Weighted phrase matching: a two-word signal outranks two one-word hits."""
    lowered = (text or "").lower()
    best: tuple[float, TaskType] = (0.0, "chat")
    for task_type, signals in _TASK_SIGNALS.items():
        score = sum(1.0 + 1.5 * (len(signal.split()) - 1) for signal in signals if signal in lowered)
        if score > best[0]:
            best = (score, task_type)
    return best[1]


def _classify_complexity(text: str, task_type: TaskType, tool_count: int) -> Complexity:
    lowered = (text or "").lower()
    connector_hits = sum(1 for c in _CONNECTORS if c in lowered)
    words = len(lowered.split())
    if task_type in ("project_scaffold", "research") or connector_hits >= 2 or words > 45 or tool_count >= 3:
        return "complex"
    if connector_hits == 1 or words > 18 or tool_count == 2 or task_type in ("coding", "document", "file_task"):
        return "moderate"
    return "simple"


def _classify_risk(text: str) -> RiskLevel:
    lowered = (text or "").lower()
    hits = [word for word in _RISKY_WORDS if word in lowered]
    if not hits:
        return "low" if any(word in lowered for word in ("write", "create", "open", "make")) else "none"
    if any(word in hits for word in ("delete", "wipe", "format", "pay", "buy", "publish", "shutdown")):
        return "high"
    return "medium"


@dataclass
class UnderstandingOutcome:
    understanding: TaskUnderstanding
    routing: RoutingDecision | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.understanding.ambiguities) and self.understanding.risk_level in ("medium", "high")


class UnderstandingEngine:
    def rule_based(self, text: str, *, tool_names: list[str] | None = None) -> TaskUnderstanding:
        task_type = _classify_type(text)
        mentioned = [name for name in (tool_names or []) if self._tool_matches(name, text)]
        complexity = _classify_complexity(text, task_type, len(mentioned))
        ambiguities = [word for word in _AMBIGUOUS if f" {word} " in f" {(text or '').lower()} "]
        return TaskUnderstanding(
            task_type=task_type,
            complexity=complexity,
            needs_tools=mentioned,
            needs_documents=task_type == "document",
            needs_memory=True,
            needs_vision="screenshot" in (text or "").lower() or "screen dikha" in (text or "").lower(),
            risk_level=_classify_risk(text),
            ambiguities=ambiguities,
            confidence=0.45 if not mentioned else 0.6,
            language=detect_language(text),
            summary=(text or "").strip()[:200],
        )

    @staticmethod
    def _tool_matches(tool_name: str, text: str) -> bool:
        lowered = (text or "").lower()
        tokens = [token for token in re.split(r"[.:_]+", tool_name) if token and token not in ("tool", "open")]
        return any(len(token) > 2 and token in lowered for token in tokens)

    def _build_prompt(self, text: str, tool_names: list[str], context: dict[str, Any] | None) -> str:
        return (
            "Read the user's request and classify it. Reply with ONE JSON object, no prose.\n\n"
            "Fields (all required):\n"
            '{"task_type": "chat|research|coding|document|file_task|project_scaffold|memory_request|'
            'home_control|device_control|unknown", '
            '"complexity": "simple|moderate|complex", '
            '"needs_tools": ["tool names from the list below, empty if none"], '
            '"needs_documents": true|false, "needs_vision": true|false, '
            '"risk_level": "none|low|medium|high", '
            '"ambiguities": ["short phrases that are unclear"], '
            '"confidence": 0.0-1.0, "summary": "one line restating the goal"}\n\n'
            f"Tools available: {json.dumps(tool_names)}\n"
            f"Session context: {json.dumps(context or {}, default=str)[:900]}\n\n"
            f"User request: {text}\n"
        )

    async def analyze(
        self,
        text: str,
        *,
        tool_names: list[str],
        context: dict[str, Any] | None = None,
        control: RunControl | None = None,
        system: str | None = None,
    ) -> UnderstandingOutcome:
        baseline = self.rule_based(text, tool_names=tool_names)
        if not text.strip():
            return UnderstandingOutcome(understanding=baseline, degraded=True, notes=["empty input"])

        messages = [ChatMessage(role="user", content=self._build_prompt(text, tool_names, context))]
        try:
            payload, run, error = await ai_router.run_json(
                RouteRequest(
                    required_capabilities={"structured_output", "tool_use"},
                    complexity="simple",
                    est_input_tokens=len(text) // 4 + 400,
                    task_type="chat",
                ),
                messages,
                system,
                max_tokens=500,
                temperature=0.0,
                control=control,
                metadata={"stage": "understanding"},
            )
        except NoModelAvailable as exc:
            return UnderstandingOutcome(
                understanding=baseline.model_copy(update={"confidence": 0.35}),
                routing=exc.decision,
                degraded=True,
                notes=[exc.decision.reason],
            )

        if error or payload is None or run is None:
            baseline.confidence = 0.4
            return UnderstandingOutcome(
                understanding=baseline,
                routing=run.decision if run else None,
                degraded=True,
                notes=[error or "model gave no classification"],
            )

        merged = self._merge(baseline, payload, tool_names)
        return UnderstandingOutcome(
            understanding=merged,
            routing=run.decision,
            degraded=run.decision.degraded,
            notes=[] if run.decision.degraded else [f"classified by {run.decision.provider}:{run.decision.model}"],
        )

    @staticmethod
    def _merge(baseline: TaskUnderstanding, payload: dict[str, Any], tool_names: list[str]) -> TaskUnderstanding:
        """Keep the machine-verified parts of the rule reading; take the rest from the model."""

        candidate = dict(payload)
        claimed_tools = [t for t in candidate.get("needs_tools", []) if isinstance(t, str)]
        candidate["needs_tools"] = [t for t in claimed_tools if t in tool_names] or baseline.needs_tools
        candidate["language"] = baseline.language
        candidate["summary"] = str(candidate.get("summary") or baseline.summary)[:300]
        if candidate.get("risk_level") in ("none", "low") and baseline.risk_level in ("medium", "high"):
            # Never let a classifier downgrade a destructive request.
            candidate["risk_level"] = baseline.risk_level
        try:
            merged = TaskUnderstanding.model_validate(
                {k: v for k, v in candidate.items() if k in TaskUnderstanding.model_fields}
            )
        except Exception as exc:
            logger.warning("understanding payload rejected by schema: %s", exc)
            return baseline.model_copy(update={"confidence": 0.4})
        if merged.confidence is None or merged.confidence == 0:
            merged.confidence = baseline.confidence
        return merged


understanding_engine = UnderstandingEngine()
