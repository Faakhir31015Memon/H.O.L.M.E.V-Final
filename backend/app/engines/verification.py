"""Verification engine: prove a step actually worked, or admit it wasn't proven.

A tool claiming `verified=True` proves nothing - the tool wrote its own report.
This engine runs a second check and keeps two ideas apart:

    verified     - the check the engine ran also passed
    independent  - that check observed something outside the tool's reply
                   (the filesystem, or a registered state observer such as the
                   device registry)

A content check on the tool's own payload can catch an empty or inconsistent
result, but it is not proof about the world, so it reports `independent=False`
and the reply says "done, unproven" instead of "done".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.engines.types import PlanStep, ToolOutcome, VerificationResult
from app.security.path_guard import PathRejected, guard, workspace_root

logger = logging.getLogger("holmev.engines.verification")
CheckFn = Callable[[PlanStep, ToolOutcome, dict[str, Any]], dict[str, Any]]

PATH_KEYS = ("path", "file_path", "folder_path", "directory", "target_path", "destination", "created_path")
CONTENT_KEYS = ("text", "content", "body", "snippets", "results", "entries", "items", "output", "message")


def _observe_device_state(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Read a device's state from the registry itself, not from the tool's reply."""

    from app.devices.registry import device_registry  # local import: no cycle, late binding

    name = str(fields.get("device") or "").strip().lower()
    room = str(fields.get("room") or "").strip().lower()
    device_type = str(fields.get("device_type") or "").strip().lower()

    for device in device_registry.devices.values():
        by_name = bool(name) and name == str(device["name"]).lower()
        by_room = bool(room and device_type) and (
            str(device["room"]).lower(), str(device["device_type"]).lower()
        ) == (room, device_type)
        if by_name or by_room:
            return dict(device.get("state") or {})
    return None


def _observe_scene_state(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Read the 3D scene from the manager itself, not from the tool's reply."""

    from app.projects.threed_manager import threed_manager  # local import: no cycle, late binding

    summary = threed_manager.scene_summary()
    wanted = str(fields.get("object_id") or "").strip()
    if wanted:
        obj = next((item for item in threed_manager.get_scene() if item["id"] == wanted), None)
        return dict(obj) if obj else None
    return summary


# An "observer" is a second source of truth the verification engine can consult.
# Without one, a state check can only compare a tool's report against the request.
STATE_OBSERVERS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "device": _observe_device_state,
    "scene": _observe_scene_state,
}


def _flatten(*sources: dict[str, Any] | None) -> dict[str, Any]:
    """Tool-reported data wins over requested params: it is what actually happened."""

    merged: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, dict):
            merged.update({k: v for k, v in source.items() if v is not None})
    return merged


class VerificationEngine:
    def _candidate_path(self, step: PlanStep, outcome: ToolOutcome) -> str | None:
        fields = _flatten(step.params, outcome.data)
        for key in PATH_KEYS:
            value = fields.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _make_path_check(self, exists: bool) -> CheckFn:
        def run(step: PlanStep, outcome: ToolOutcome, spec: dict[str, Any]) -> dict[str, Any]:
            raw = self._candidate_path(step, outcome)
            if raw is None:
                return {
                    "kind": "path_absent" if not exists else "path_exists",
                    "passed": False,
                    "independent": True,
                    "detail": "neither the step nor the tool reported a path to check",
                }
            try:
                guarded = guard(raw, root=workspace_root())
            except PathRejected as exc:
                return {
                    "kind": "path_absent" if not exists else "path_exists",
                    "passed": False,
                    "independent": True,
                    "detail": f"refused to verify a path outside the workspace: {exc.reason}",
                }
            present = guarded.resolved.exists()
            expected = "must exist" if exists else "must be gone"
            return {
                "kind": "path_exists" if exists else "path_absent",
                "passed": present is exists,
                "independent": True,
                "detail": f"{guarded.relative} exists={present}, {expected}",
                "evidence": str(guarded.resolved)[:200],
            }

        return run

    @staticmethod
    def _content_size(fields: dict[str, Any]) -> int:
        for key in CONTENT_KEYS:
            value = fields.get(key)
            if isinstance(value, str) and value.strip():
                return len(value.strip())
            if isinstance(value, (list, tuple)) and value:
                return len(value)
            if isinstance(value, dict) and value:
                return len(value)
        return 0

    @staticmethod
    def _check_non_empty(step: PlanStep, outcome: ToolOutcome, spec: dict[str, Any]) -> dict[str, Any]:
        fields = _flatten(step.params, outcome.data)
        size = VerificationEngine._content_size(fields)
        return {
            "kind": "non_empty",
            "passed": size > 0,
            "independent": False,
            "detail": f"result carries {size} character(s)/item(s) of content",
        }

    @staticmethod
    def _check_state_matches(step: PlanStep, outcome: ToolOutcome, spec: dict[str, Any]) -> dict[str, Any]:
        expected = spec.get("expect")
        if not isinstance(expected, dict) or not expected:
            return {
                "kind": "state_matches",
                "passed": False,
                "independent": False,
                "detail": "no expected state was declared, so nothing could be matched",
            }

        observer = str(spec.get("observe") or "")
        if observer:
            read_state = STATE_OBSERVERS.get(observer)
            if read_state is None:
                return {
                    "kind": "state_matches",
                    "passed": False,
                    "independent": True,
                    "detail": f"no state observer named '{observer}' is registered on this device",
                }
            actual = read_state(_flatten(step.params, outcome.data)) or {}
            source = f"read back from {observer}"
            independent = True
        else:
            actual = _flatten(outcome.data)
            source = "the tool's own report"
            independent = False

        mismatched = {
            key: (want, _deep_get(actual, key))
            for key, want in expected.items()
            if _leaf(_deep_get(actual, key)) != _leaf(want)
        }
        return {
            "kind": "state_matches",
            "passed": not mismatched,
            "independent": independent,
            "detail": (
                f"state matches ({source})"
                if not mismatched
                else "state differs: " + "; ".join(f"{k} wanted {w} got {g}" for k, (w, g) in mismatched.items())
            ),
        }

    @staticmethod
    def _check_contains(step: PlanStep, outcome: ToolOutcome, spec: dict[str, Any]) -> dict[str, Any]:
        needle = str(spec.get("text") or spec.get("contains") or "")
        haystack = " ".join(
            str(value)
            for value in _flatten(outcome.data).values()
            if isinstance(value, (str, int, float))
        )
        if not needle:
            return {"kind": "contains", "passed": False, "independent": False, "detail": "nothing declared to look for"}
        return {
            "kind": "contains",
            "passed": needle.lower() in haystack.lower(),
            "independent": False,
            "detail": f"looked for '{needle[:60]}' in the returned content",
        }

    @staticmethod
    def _check_count_at_least(step: PlanStep, outcome: ToolOutcome, spec: dict[str, Any]) -> dict[str, Any]:
        want = int(spec.get("count", 1))
        fields = _flatten(outcome.data)
        for key in CONTENT_KEYS:
            value = fields.get(key)
            if isinstance(value, (list, tuple)):
                return {
                    "kind": "count_at_least",
                    "passed": len(value) >= want,
                    "independent": False,
                    "detail": f"{key} has {len(value)} item(s), wanted at least {want}",
                }
        return {
            "kind": "count_at_least",
            "passed": False,
            "independent": False,
            "detail": "no list in the result to count",
        }

    @staticmethod
    def _check_json_shape(step: PlanStep, outcome: ToolOutcome, spec: dict[str, Any]) -> dict[str, Any]:
        required = spec.get("required_keys")
        if not isinstance(required, list) or not required:
            return {"kind": "json_shape", "passed": False, "independent": False, "detail": "no required keys declared"}
        data = outcome.data or {}
        missing = [key for key in required if key not in data]
        return {
            "kind": "json_shape",
            "passed": not missing,
            "independent": False,
            "detail": "all declared keys present" if not missing else f"missing keys: {', '.join(map(str, missing))}",
        }

    def _checker(self, kind: str) -> CheckFn | None:
        """Only these check types exist; anything else reports honestly as unimplemented."""

        if kind in ("path_exists", "path_absent"):
            return self._make_path_check(kind == "path_exists")
        return {
            "non_empty": self._check_non_empty,
            "state_matches": self._check_state_matches,
            "contains": self._check_contains,
            "count_at_least": self._check_count_at_least,
            "json_shape": self._check_json_shape,
        }.get(kind)

    def verify(self, step: PlanStep, outcome: ToolOutcome) -> VerificationResult:
        """Re-check the world; never accept the tool's own claim as proof."""

        self_report = {
            "kind": "tool_self_report",
            "passed": bool(outcome.success),
            "independent": False,
            "detail": (
                f"{step.tool} reported success={outcome.success}, "
                f"self-declared verified={outcome.metadata.get('tool_claimed')}"
            ),
        }
        checks = [self_report]

        if outcome.error:
            checks.append(
                {"kind": "error_free", "passed": False, "independent": True, "detail": str(outcome.error)[:200]}
            )
            return VerificationResult(
                verified=False, checks=checks, independent=False,
                reason=f"step failed: {str(outcome.error)[:160]}",
            )

        spec = step.verification if isinstance(step.verification, dict) else {}
        kind = str(spec.get("type") or "tool_success")

        if kind in ("none", "tool_success", ""):
            # Nothing observable was declared to check, so all we have is the tool's word.
            return VerificationResult(
                verified=bool(outcome.success),
                checks=checks,
                independent=False,
                reason=(
                    "tool reported success; nothing observable was declared, so this is NOT independently verified"
                    if outcome.success
                    else "tool reported failure"
                ),
            )

        checker = self._checker(kind)
        if checker is None:
            checks.append(
                {"kind": "unknown_check", "passed": False, "independent": True, "detail": f"no such check '{kind}'"}
            )
            return VerificationResult(
                verified=False, checks=checks, independent=False,
                reason=f"verification type '{kind}' is not implemented",
            )

        extra_check = checker(step, outcome, spec)
        checks.append(extra_check)
        verified = bool(outcome.success) and bool(extra_check["passed"])
        independent = verified and bool(extra_check.get("independent"))
        return VerificationResult(
            verified=verified,
            checks=checks,
            independent=independent,
            reason=(
                extra_check["detail"] if verified
                else f"not verified: {extra_check['detail']}"
            ),
        )

    def verify_chain(self, steps: list[PlanStep], outcomes: dict[str, ToolOutcome]) -> dict[str, VerificationResult]:
        return {
            step.id: self.verify(step, outcomes.get(step.id) or ToolOutcome(success=False, error="never executed"))
            for step in steps
        }

    @staticmethod
    def least_verified(results: dict[str, VerificationResult]) -> VerificationResult | None:
        """A run is only as verified as its worst step: proven-failed first, then unproven."""

        for result in results.values():
            if not result.verified:
                return result
        return next((r for r in results.values() if not r.independent), None)


def _deep_get(data: dict[str, Any], key: str) -> Any:
    """Tools report {'power': False} and {'state': {'power': False}}; match either."""

    if key in data:
        return data[key]
    for value in data.values():
        if isinstance(value, dict):
            found = _deep_get(value, key)
            if found is not None:
                return found
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, dict):
                    found = _deep_get(item, key)
                    if found is not None:
                        return found
    return None


def _leaf(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _leaf(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_leaf(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


verification_engine = VerificationEngine()
