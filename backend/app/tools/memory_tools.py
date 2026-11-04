"""Memory tools talk to the persistent engine, not a process-local list.

The previous version wrote into `self.memories` — a plain Python list that vanished
on restart — while describing itself as "long-term memory" and returning
`verified=True`. Retrieval answered a no-match query by handing back the first five
unrelated memories, which is fabrication dressed as a lookup.

Both paths now use the DB-backed engine, an empty result stays empty, and a stored
fact arrives as a proposal the user confirms rather than a claim the brain made about
them.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolResult


class MemoryStoreInput(BaseModel):
    category: str = Field(default="fact", description="Preference, fact, alias or room_mapping")
    key: str = Field(description="Memory key or topic identifier")
    value: str = Field(description="Memory text value or fact to store")


class MemoryStoreTool(BaseTool):
    name = "memory.store"
    description = (
        "Proposes a fact, preference or alias to H.O.L.M.E.V persistent memory. "
        "It is stored as pending until the user confirms it."
    )
    category = "memory"
    permission_level = 1
    input_schema = MemoryStoreInput

    async def _run(self, category: str = "fact", key: str = "", value: str = "", **kwargs: Any) -> ToolResult:
        from app.engines.memory import MemoryBlocked, memory_engine

        labelled = f"{category.strip().lower()}:{key.strip()}" if category and category.strip() else key
        try:
            result = await memory_engine.propose(key=labelled, value=value, layer="semantic")
        except MemoryBlocked as exc:
            return ToolResult(
                success=False, verified=False, error=str(exc), data={"stored": False, "performed": False}
            )

        if not result.stored:
            return ToolResult(
                success=False,
                verified=False,
                error=result.blocked_reason or "the memory engine refused this proposal",
                data={"stored": False, "performed": False, "reason": result.blocked_reason},
            )

        return ToolResult(
            success=True,
            verified=False,
            data={
                **result.as_dict(),
                "category": category,
                "confirm_with": f"POST /api/v1/brain/memories/{result.record.id if result.record else ''}/confirm",
                "note": "written to the database as pending; it is not used until the user confirms it",
            },
            error=None,
        )


class MemoryRetrieveInput(BaseModel):
    query: str = Field(description="Query string or keyword to search memory for")
    session: str = Field(default="default_session", description="Session whose working memory may also match")


class MemoryRetrieveTool(BaseTool):
    name = "memory.retrieve"
    description = "Searches confirmed long-term memory (plus this session's working memory) for matching facts."
    category = "memory"
    permission_level = 0
    input_schema = MemoryRetrieveInput

    async def _run(self, query: str = "", session: str = "default_session", **kwargs: Any) -> ToolResult:
        from app.engines.memory import memory_engine

        hits = await memory_engine.retrieve(query, session=session)
        if not hits:
            # No padding, no "here are five other things you might have meant".
            return ToolResult(
                success=True,
                verified=False,
                data={"query": query, "memories": [], "match_count": 0, "note": "nothing confirmed matched"},
                error=None,
            )

        return ToolResult(
            success=True,
            verified=False,
            data={
                "query": query,
                "match_count": len(hits),
                "memories": [
                    {**hit.record.as_dict(), "score": round(hit.score, 3), "matched_terms": hit.terms,
                     "source": hit.source}
                    for hit in hits
                ],
            },
            error=None,
        )
