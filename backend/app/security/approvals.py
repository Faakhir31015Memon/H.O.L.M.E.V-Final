"""Approval grants: single-use, parameter-bound, expiring.

An approval proves the user agreed to *this exact action*. Running different
parameters than the ones shown is rejected, and a grant cannot be replayed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from app.config.settings import settings
from app.database.models import Approval
from app.database.session import session_scope


def canonical_param_hash(tool: str, params: dict[str, Any]) -> str:
    """Stable hash over sorted JSON so equal params always compare equal."""

    payload = json.dumps({"tool": tool, "params": params}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class ApprovalNotFound(Exception):
    pass


class ApprovalRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ApprovalService:
    async def create(
        self,
        *,
        tool: str,
        params: dict[str, Any],
        permission_level: int,
        summary: str,
        run_id: str | None = None,
        step_id: str | None = None,
        expires_in_s: int | None = None,
    ) -> Approval:
        ttl = expires_in_s if expires_in_s is not None else settings.APPROVAL_EXPIRY_S
        now = datetime.now(timezone.utc)
        record = Approval(
            run_id=run_id,
            step_id=step_id,
            tool=tool,
            params=params,
            param_hash=canonical_param_hash(tool, params),
            permission_level=permission_level,
            summary=summary,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        async with session_scope() as session:
            session.add(record)
            await session.flush()
            await session.refresh(record)
        return record

    async def get(self, approval_id: str) -> Approval:
        async with session_scope() as session:
            record = await session.get(Approval, approval_id)
        if record is None:
            raise ApprovalNotFound(f"No approval with id '{approval_id}'.")
        return record

    async def list_pending(self) -> list[Approval]:
        await self.expire_stale()
        async with session_scope() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.status == "pending")
                .order_by(Approval.created_at.desc())
                .limit(100)
            )
            return list(result.scalars().all())

    async def decide(
        self, approval_id: str, *, approved: bool, decided_by: str = "user"
    ) -> Approval:
        record = await self.get(approval_id)
        if record.status != "pending":
            raise ApprovalRejected(f"Approval '{approval_id}' is already '{record.status}'.")
        if _as_utc(record.expires_at) <= datetime.now(timezone.utc):
            await self._mark(approval_id, "expired")
            raise ApprovalRejected("That approval expired before it was answered. Ask again.")
        await self._mark(approval_id, "approved" if approved else "denied", decided_by=decided_by)
        return await self.get(approval_id)

    async def consume(self, approval_id: str, *, tool: str, params: dict[str, Any]) -> Approval:
        """Validate then burn the grant. Any mismatch raises."""

        record = await self.get(approval_id)
        now = datetime.now(timezone.utc)

        if record.status == "pending":
            if _as_utc(record.expires_at) <= now:
                await self._mark(approval_id, "expired")
                raise ApprovalRejected("Approval expired without a decision.")
            raise ApprovalRejected("Approval was never granted - the user still has to approve it.")
        if record.status == "denied":
            raise ApprovalRejected("The user denied this action.")
        if record.status == "consumed":
            raise ApprovalRejected("This approval was already used; consequential actions need a fresh grant.")
        if record.status == "expired":
            raise ApprovalRejected("Approval expired without a decision.")

        if record.tool != tool:
            raise ApprovalRejected(f"Approval was granted for '{record.tool}', not '{tool}'.")
        if record.param_hash != canonical_param_hash(tool, params):
            raise ApprovalRejected(
                "The parameters differ from the ones the user approved; execution blocked."
            )

        await self._mark(approval_id, "consumed", consumed_at=now)
        return await self.get(approval_id)

    async def expire_stale(self) -> int:
        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            result = await session.execute(
                update(Approval)
                .where(Approval.status == "pending", Approval.expires_at < now)
                .values(status="expired")
            )
            return int(result.rowcount or 0)

    async def cancel_pending_for_run(self, run_id: str) -> int:
        async with session_scope() as session:
            result = await session.execute(
                update(Approval)
                .where(Approval.run_id == run_id, Approval.status == "pending")
                .values(status="cancelled", decided_at=datetime.now(timezone.utc), decided_by="emergency_stop")
            )
            return int(result.rowcount or 0)

    async def cancel_pending_for_runs(self, run_ids: set[str]) -> int:
        total = 0
        for run_id in run_ids:
            if run_id:
                total += await self.cancel_pending_for_run(run_id)
        return total

    async def cancel_all_pending(self) -> int:
        """Emergency stop voids every outstanding request, not just active runs."""

        async with session_scope() as session:
            result = await session.execute(
                update(Approval)
                .where(Approval.status == "pending")
                .values(status="cancelled", decided_at=datetime.now(timezone.utc), decided_by="emergency_stop")
            )
            return int(result.rowcount or 0)

    async def _mark(
        self, approval_id: str, status: str, *, decided_by: str | None = None,
        consumed_at: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if decided_by is not None or status in {"approved", "denied"}:
            values["decided_by"] = decided_by
            values["decided_at"] = datetime.now(timezone.utc)
        if consumed_at is not None:
            values["consumed_at"] = consumed_at
        async with session_scope() as session:
            await session.execute(update(Approval).where(Approval.id == approval_id).values(**values))

    @staticmethod
    def describe(record: Approval) -> dict[str, Any]:
        return {
            "id": record.id,
            "tool": record.tool,
            "params": record.params,
            "summary": record.summary,
            "permission_level": record.permission_level,
            "status": record.status,
            "expires_at": _as_utc(record.expires_at).isoformat() if record.expires_at else None,
            "run_id": record.run_id,
            "step_id": record.step_id,
        }


approval_service = ApprovalService()
