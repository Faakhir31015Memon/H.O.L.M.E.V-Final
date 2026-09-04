from typing import Optional, Any
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult

class MemoryStoreInput(BaseModel):
    category: str = Field(description="Memory category: preference, fact, alias, room_mapping")
    key: str = Field(description="Memory key or topic identifier")
    value: str = Field(description="Memory text value or fact to store")

class MemoryStoreTool(BaseTool):
    name = "memory.store"
    description = "Stores a fact, preference, or piece of information into H.O.L.M.E.V long-term memory."
    category = "memory"
    permission_level = 1
    input_schema = MemoryStoreInput

    async def _run(self, category: str, key: str, value: str, **kwargs: Any) -> ToolResult:
        from app.memory.store import memory_store
        
        item = await memory_store.store_memory(category=category, key=key, value=value)
        return ToolResult(
            success=True,
            verified=True,
            data={"memory_id": item["id"], "key": key, "value": value},
            error=None
        )

class MemoryRetrieveInput(BaseModel):
    query: str = Field(description="Query string or keyword to search memory")

class MemoryRetrieveTool(BaseTool):
    name = "memory.retrieve"
    description = "Retrieves stored facts, user preferences, or device aliases from long-term memory."
    category = "memory"
    permission_level = 0
    input_schema = MemoryRetrieveInput

    async def _run(self, query: str, **kwargs: Any) -> ToolResult:
        from app.memory.store import memory_store
        
        results = await memory_store.retrieve_memories(query=query)
        return ToolResult(
            success=True,
            verified=True,
            data={"query": query, "memories": results},
            error=None
        )
