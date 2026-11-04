"""Append-only audit trail with secret redaction.

Every consequential decision - allowed, denied, executed, failed, undone - is
recorded so the user can see what the brain actually did.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database.models import AuditEntry
from app.database.session import session_scope

_SECRET_KEY_NAMES = ("password", "passwd", "secret", "token", "api_key", "apikey", "authorization", "cookie")

_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
)

REDACTED = "***redacted***"


def _looks_secret_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def contains_secret_value(text: str) -> bool:
    """Public check: does this string look like it carries a credential?"""

    return bool(text) and _looks_secret_value(text)


def scrub_secret_patterns(text: str, replacement: str = "[redacted credential]") -> str:
    """Replace every credential-shaped substring found in `text`."""

    if not text:
        return text
    out = text
    for pattern in _SECRET_VALUE_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact(value: Any, *, parent_key: str = "") -> Any:
    """Recursively strip anything that resembles a credential."""

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if any(needle in str(key).lower() for needle in _SECRET_KEY_NAMES):
                out[str(key)] = REDACTED
            else:
                out[str(key)] = redact(item, parent_key=str(key))
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        if _looks_secret_value(value):
            return REDACTED
        if parent_key and any(needle in parent_key.lower() for needle in _SECRET_KEY_NAMES):
            return REDACTED
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


class AuditLog:
    async def record(
        self,
        *,
        action: str,
        outcome: str = "allowed",
        actor: str = "user",
        run_id: str | None = None,
        tool: str | None = None,
        params: dict[str, Any] | None = None,
        permission_level: int | None = None,
        approval_id: str | None = None,
        error: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            ts=datetime.now(timezone.utc),
            actor=actor,
            run_id=run_id,
            tool=tool,
            action=action,
            sanitized_params=redact(params or {}),
            permission_level=permission_level,
            approval_id=approval_id,
            outcome=outcome,
            error=(error or None) and str(error)[:2000],
        )
        async with session_scope() as session:
            session.add(entry)
            await session.flush()
            await session.refresh(entry)
        return entry

    async def query(
        self,
        *,
        run_id: str | None = None,
        tool: str | None = None,
        outcome: str | None = None,
        limit: int = 200,
    ) -> list[AuditEntry]:
        stmt = select(AuditEntry).order_by(AuditEntry.ts.desc()).limit(min(limit, 1000))
        if run_id:
            stmt = stmt.where(AuditEntry.run_id == run_id)
        if tool:
            stmt = stmt.where(AuditEntry.tool == tool)
        if outcome:
            stmt = stmt.where(AuditEntry.outcome == outcome)
        async with session_scope() as session:
            return list((await session.execute(stmt)).scalars().all())

    async def export(self, fmt: str = "json") -> str:
        import csv
        import io
        import json

        entries = await self.query(limit=1000)
        rows = [
            {
                "id": e.id,
                "ts": e.ts.isoformat() if e.ts else "",
                "actor": e.actor,
                "run_id": e.run_id or "",
                "tool": e.tool or "",
                "action": e.action,
                "params": json.dumps(e.sanitized_params or {}, sort_keys=True, default=str),
                "permission_level": e.permission_level,
                "approval_id": e.approval_id or "",
                "outcome": e.outcome,
                "error": e.error or "",
            }
            for e in entries
        ]
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else ["id"])
            writer.writeheader()
            writer.writerows(rows)
            return buffer.getvalue()
        return json.dumps(rows, indent=2)


audit_log = AuditLog()
