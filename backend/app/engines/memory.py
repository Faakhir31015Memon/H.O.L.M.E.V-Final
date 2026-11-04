"""Memory engine: four layers, nothing remembered without the user saying yes.

Layers
    working     - this session only, held in RAM, never written to disk
    episodic    - what happened (run summaries the user can ask about later)
    semantic    - stable facts and preferences ("my favourite room is the hall")
    procedural  - how the user likes things done ("confirm before calling mom")

Rules enforced here, not suggested:
    * a proposal lands in `pending` and only the user moves it to `active`
    * sensitive categories (credentials, health, religion, ethnicity, sexuality,
      politics, biometrics) are refused outright - they are never stored
    * retrieval is BM25 + recency + confidence, so ranking is explainable
    * sessions cannot read each other's working layer
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import delete, select

from app.config.settings import settings
from app.database.models import BrainMemory
from app.database.session import session_scope
from app.engines.types import ContextTraceItem
from app.security.audit import contains_secret_value

logger = logging.getLogger("holmev.engines.memory")

Layer = Literal["working", "episodic", "semantic", "procedural"]
LAYERS: tuple[str, ...] = ("working", "episodic", "semantic", "procedural")
STATE_TTL_TURNS = 40

# Refused before anything is written. Deliberately broader than "obvious secrets":
# a home assistant that stores health or belief data becomes a liability the user
# did not agree to.
SENSITIVE_BLOCKLIST: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("credential", re.compile(r"\b(password|passphrase|pin|otp|cvv|secret\s*q|api[_ -]?key)\b", re.I)),
    ("payment_data", re.compile(r"\b(credit card|debit card|card number|iban|routing number)\b", re.I)),
    # CNIC/SSN before the bare digit run, so the user is told the real reason.
    ("government_id", re.compile(r"\b(cnic|ssn|social security|passport number|drivers? licence)\b", re.I)),
    ("digits_sequence", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("health", re.compile(r"\b(diabetes|hiv|aids|cancer|depress|anxiety|bipolar|pregnan|medication|therapy)\b", re.I)),
    ("religion", re.compile(r"\b(religion|religious|atheist|conversion to islam|church|mandir)\b", re.I)),
    ("ethnicity", re.compile(r"\b(ethnicity|race|caste|tribe)\b", re.I)),
    ("sexuality", re.compile(r"\b(sexual orientation|gay|lesbian|transgender|bisexual)\b", re.I)),
    ("political", re.compile(r"\b(political party|votes for|political affiliation)\b", re.I)),
    ("biometric", re.compile(r"\b(fingerprint|iris scan|face template|voiceprint)\b", re.I)),
)


class MemoryBlocked(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class MemoryRecord:
    id: str
    layer: str
    key: str
    value: str
    state: str = "pending"
    scope: str = "global"
    confidence: float = 0.5
    source_run_id: str | None = None
    session: str | None = None
    created_at: str = ""
    updated_at: str = ""
    confirmed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: BrainMemory) -> MemoryRecord:
        return cls(
            id=row.id,
            layer=row.category if row.category in LAYERS else "semantic",
            key=row.key,
            value=row.value,
            state=row.state,
            scope=row.scope,
            confidence=float(row.confidence or 0.5),
            source_run_id=row.source_run_id,
            created_at=_stamp(row.created_at),
            updated_at=_stamp(row.updated_at),
            confirmed_at=_stamp(row.confirmed_at) if row.confirmed_at else None,
        )


@dataclass
class StoreResult:
    stored: bool
    record: MemoryRecord | None = None
    blocked_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "stored": self.stored,
            "id": self.record.id if self.record else None,
            "state": self.record.state if self.record else None,
            "blocked_reason": self.blocked_reason,
        }


@dataclass
class MemoryHit:
    record: MemoryRecord
    score: float
    terms: list[str] = field(default_factory=list)
    recency: float = 0.0
    source: str = "long_term"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.record.id,
            "layer": self.record.layer,
            "key": self.record.key,
            "value": self.record.value,
            "state": self.record.state,
            "confidence": self.record.confidence,
            "score": round(self.score, 4),
            "matched": self.terms,
            "recency": round(self.recency, 3),
            "source": self.source,
        }


def _stamp(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sensitive_reason(key: str, value: str) -> str | None:
    """Return the policy label that forbids this memory, or None when it is safe."""

    # Underscores are normalised so a snake_case key like `wifi_password` cannot
    # slip past a word-boundary pattern.
    text = f"{key}: {value}".replace("_", " ")
    for label, pattern in SENSITIVE_BLOCKLIST:
        if pattern.search(text):
            return f"not stored - '{label}' is a protected category"
    if contains_secret_value(text):
        return "not stored - the content looks like a live credential"
    return None


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


class MemoryEngine:
    """Working layer in RAM per session; the other three layers live in SQLite."""

    def __init__(self) -> None:
        self._working: dict[str, deque[MemoryRecord]] = defaultdict(lambda: deque(maxlen=STATE_TTL_TURNS))

    # ------------------------------------------------------------------ writing

    async def propose(
        self,
        *,
        key: str,
        value: str,
        layer: str = "semantic",
        confidence: float = 0.5,
        source_run_id: str | None = None,
        session: str | None = None,
        state: str = "pending",
    ) -> StoreResult:
        if state not in ("pending", "active"):
            raise MemoryBlocked(f"unknown memory state '{state}'")
        clean_key = (key or "").strip()[:200]
        clean_value = (value or "").strip()
        if not clean_key or not clean_value:
            raise MemoryBlocked("memory needs both a key and a value")
        if len(clean_value) > 4000:
            raise MemoryBlocked("memory value is too long to store verbatim")

        blocked = sensitive_reason(clean_key, clean_value)
        if blocked:
            logger.info("memory proposal refused: %s", blocked)
            return StoreResult(stored=False, blocked_reason=blocked)

        row = BrainMemory(
            category=layer if layer in LAYERS else "semantic",
            key=clean_key,
            value=clean_value[:4000],
            state=state,
            scope="global",
            source_run_id=source_run_id,
            source_session=session,
            confidence=max(0.0, min(1.0, float(confidence))),
        )
        async with session_scope() as db:
            db.add(row)
            await db.flush()
            record = MemoryRecord.from_row(row)
        return StoreResult(stored=True, record=record)

    def remember_turn(self, session: str, role: str, text: str) -> MemoryRecord:
        """Conversation stays in the working layer: this session, this process, gone on restart."""

        record = MemoryRecord(
            id=f"work_{len(self._working[session]) + 1}",
            layer="working",
            key=f"{role}_turn",
            value=(text or "")[:1500],
            state="active",
            scope="session",
            confidence=1.0,
            session=session,
            created_at=_now().isoformat(),
            updated_at=_now().isoformat(),
        )
        self._working[session].append(record)
        return record

    def working(self, session: str) -> list[MemoryRecord]:
        return list(self._working.get(session, ()))

    def clear_working(self, session: str | None = None) -> None:
        if session is None:
            self._working.clear()
        else:
            self._working.pop(session, None)

    # ------------------------------------------------------------------ confirmation

    async def set_state(self, memory_id: str, state: str) -> MemoryRecord | None:
        if state not in ("pending", "active", "rejected"):
            raise MemoryBlocked(f"cannot move a memory to '{state}'")
        async with session_scope() as db:
            row = await db.get(BrainMemory, memory_id)
            if row is None:
                return None
            row.state = state
            row.confirmed_at = _now() if state == "active" else None
            await db.flush()
            return MemoryRecord.from_row(row)

    async def confirm(self, memory_id: str) -> MemoryRecord | None:
        return await self.set_state(memory_id, "active")

    async def reject(self, memory_id: str) -> MemoryRecord | None:
        return await self.set_state(memory_id, "rejected")

    async def forget(self, memory_id: str) -> bool:
        async with session_scope() as db:
            row = await db.get(BrainMemory, memory_id)
            if row is None:
                return False
            await db.delete(row)
        return True

    async def forget_matching(self, query: str, session: str | None = None) -> list[str]:
        """Delete every active/pending memory the query ranks highly against."""

        hits = await self.retrieve(query, session=session or "default", limit=50, states=("pending", "active"))
        removed: list[str] = []
        for hit in hits:
            if await self.forget(hit.record.id):
                removed.append(hit.record.id)
        return removed

    async def purge_all(self) -> int:
        async with session_scope() as db:
            result = await db.execute(delete(BrainMemory))
            self.clear_working()
            return int(result.rowcount or 0)

    # ------------------------------------------------------------------ reading

    async def list_memories(
        self, *, state: str | None = "active", layer: str | None = None, limit: int = 200
    ) -> list[MemoryRecord]:
        stmt = select(BrainMemory)
        if state:
            stmt = stmt.where(BrainMemory.state == state)
        if layer:
            stmt = stmt.where(BrainMemory.category == layer)
        stmt = stmt.order_by(BrainMemory.updated_at.desc()).limit(limit)
        async with session_scope() as db:
            rows = (await db.execute(stmt)).scalars().all()
            return [MemoryRecord.from_row(row) for row in rows]

    async def retrieve(
        self,
        query: str,
        *,
        session: str,
        limit: int = 6,
        states: tuple[str, ...] = ("active",),
        include_working: bool = True,
    ) -> list[MemoryHit]:
        terms = _tokenize(query)
        if not terms:
            return []

        candidates = await self._candidates(states)
        scores = _bm25(terms, candidates)
        hits: list[MemoryHit] = []
        for row, (score, matched) in zip(candidates, scores, strict=True):
            if score <= 0:
                continue
            record = MemoryRecord.from_row(row)
            recency = _recency_weight(record.updated_at)
            hits.append(
                MemoryHit(
                    record=record,
                    score=score * (0.75 + 0.25 * recency) * (0.6 + 0.4 * record.confidence),
                    terms=matched,
                    recency=recency,
                )
            )

        if include_working:
            working = self.working(session)
            working_scores = _bm25(terms, working)
            for record, (score, matched) in zip(working, working_scores, strict=True):
                if score <= 0:
                    continue
                hits.append(
                    MemoryHit(record=record, score=score * 1.15, terms=matched, recency=1.0, source="working")
                )

        hits.sort(key=lambda hit: (-hit.score, hit.record.id))
        return hits[:limit]

    async def _candidates(self, states: tuple[str, ...]) -> list[BrainMemory]:
        stmt = select(BrainMemory).where(BrainMemory.state.in_(states))
        if settings.MEMORY_MAX_ROWS:
            stmt = stmt.order_by(BrainMemory.updated_at.desc()).limit(settings.MEMORY_MAX_ROWS)
        async with session_scope() as db:
            return list((await db.execute(stmt)).scalars().all())

    async def context_pack(
        self, query: str, *, session: str, budget_tokens: int | None = None
    ) -> tuple[list[dict[str, Any]], list[ContextTraceItem]]:
        """Memories that fit the prompt budget, with the reason each one is there."""

        budget = budget_tokens or settings.MEMORY_TOKEN_BUDGET
        hits = await self.retrieve(query, session=session, limit=20)
        included: list[dict[str, Any]] = []
        trace: list[ContextTraceItem] = []
        spent = 0
        for hit in hits:
            payload = hit.as_dict()
            text = f"{payload['key']}: {payload['value']}"
            cost = max(1, len(text) // 4)
            if spent + cost > budget:
                trace.append(
                    ContextTraceItem(
                        kind="memory", label=payload["key"], tokens_est=cost, included=False,
                        reason="over the memory token budget",
                    )
                )
                continue
            spent += cost
            payload["tokens_est"] = cost
            included.append(payload)
            trace.append(
                ContextTraceItem(
                    kind="memory",
                    label=payload["key"],
                    tokens_est=cost,
                    included=True,
                    reason=f"matched {', '.join(payload['matched'])[:60]} (score {payload['score']})",
                )
            )
        return included, trace

    async def pending_count(self) -> int:
        async with session_scope() as db:
            rows = (await db.execute(select(BrainMemory.id).where(BrainMemory.state == "pending"))).all()
            return len(rows)

    # ------------------------------------------------------------------ export

    async def export(self, fmt: str = "json") -> str:
        rows = await self.list_memories(state=None, limit=5000)
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["id", "layer", "key", "value", "state", "confidence", "updated_at"])
            for record in rows:
                writer.writerow(
                    [record.id, record.layer, record.key, record.value, record.state,
                     record.confidence, record.updated_at]
                )
            return buffer.getvalue()
        return json.dumps([record.as_dict() for record in rows], indent=2, default=str)


def _layer_of(row: Any) -> str:
    return str(getattr(row, "category", None) or getattr(row, "layer", None) or "")


def _bm25(terms: list[str], rows: list[Any]) -> list[tuple[float, list[str]]]:
    """Okapi BM25 (k1=1.5, b=0.75). Small corpus, so this is exact rather than indexed."""

    documents = [
        _tokenize(getattr(row, "key", "") or "") * 2
        + _tokenize(getattr(row, "value", "") or "")
        + _tokenize(_layer_of(row).replace("_", " "))
        for row in rows
    ]
    if not documents:
        return []

    lengths = [len(doc) or 1 for doc in documents]
    avg_len = sum(lengths) / len(lengths)
    df: dict[str, int] = defaultdict(int)
    counts: list[dict[str, int]] = []
    for doc in documents:
        tf: dict[str, int] = defaultdict(int)
        for token in doc:
            tf[token] += 1
        counts.append(tf)
        for token in set(doc):
            df[token] += 1

    k1, b, n = 1.5, 0.75, len(documents)
    results: list[tuple[float, list[str]]] = []
    for index, counts_for_doc in enumerate(counts):
        score = 0.0
        matched: list[str] = []
        for term in dict.fromkeys(terms):
            freq = counts_for_doc.get(term, 0)
            if not freq:
                continue
            matched.append(term)
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            norm = freq * (k1 + 1) / (freq + k1 * (1 - b + b * lengths[index] / avg_len))
            score += idf * norm
        results.append((score, matched))
    return results


def _recency_weight(stamp: str) -> float:
    """Half-life of 30 days; a memory from today is worth 1.0."""

    if not stamp:
        return 0.5
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return 0.5
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (_now() - moment).total_seconds() / 86400.0)
    return 0.5 ** (age_days / 30.0)


memory_engine = MemoryEngine()
