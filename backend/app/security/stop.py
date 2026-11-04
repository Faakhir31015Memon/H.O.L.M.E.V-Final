"""Emergency stop: one switch that halts runs and freezes every tool.

Re-enabling requires an explicit user action. Nothing else can clear this flag.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.security.approvals import approval_service


class EmergencyStop:
    def __init__(self) -> None:
        self.engaged = False
        self.engaged_at: datetime | None = None
        self.reason: str = ""
        self._cancelled_runs: set[str] = set()
        self._controls: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def register_control(self, run_id: str, control) -> None:
        self._controls[run_id] = control

    def release_control(self, run_id: str) -> None:
        self._controls.pop(run_id, None)

    def active_run_ids(self) -> list[str]:
        """Which runs are live right now, for the UI and the audit trail."""

        return sorted(self._controls)

    async def engage(self, reason: str = "user pressed STOP") -> dict[str, Any]:
        async with self._lock:
            self.engaged = True
            self.engaged_at = datetime.now(timezone.utc)
            self.reason = reason

        for run_id, control in list(self._controls.items()):
            control.cancel()
            self._cancelled_runs.add(run_id)

        voided = await approval_service.cancel_all_pending()

        return {
            "engaged": True,
            "reason": reason,
            "runs_cancelled": len(self._cancelled_runs),
            "approvals_voided": voided,
            "engaged_at": self.engaged_at.isoformat() if self.engaged_at else None,
        }

    async def resume(self) -> dict[str, Any]:
        async with self._lock:
            self.engaged = False
            self.engaged_at = None
            self.reason = ""
            self._cancelled_runs.clear()
        return {"engaged": False, "resumed_at": datetime.now(timezone.utc).isoformat()}

    def guard(self, run_id: str | None = None) -> None:
        """Raise if execution is not permitted right now."""

        if self.engaged:
            raise StopEngaged(
                "H.O.L.M.E.V is paused. Nothing will read, write, or act until you press Resume."
            )
        if run_id and run_id in self._cancelled_runs:
            raise StopEngaged("This run was cancelled.")

    def status(self) -> dict[str, Any]:
        return {
            "engaged": self.engaged,
            "reason": self.reason,
            "engaged_at": self.engaged_at.isoformat() if self.engaged_at else None,
            "active_runs": len(self._controls),
        }


class StopEngaged(RuntimeError):
    pass


emergency_stop = EmergencyStop()
