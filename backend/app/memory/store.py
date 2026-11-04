import uuid
from datetime import datetime, timezone
from typing import Any


class MemoryStore:
    def __init__(self):
        self.memories: list[dict[str, Any]] = [
            {
                "id": "mem_pref_room",
                "category": "preference",
                "key": "preferred_room",
                "value": "Bedroom",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]

    async def store_memory(self, category: str, key: str, value: str) -> dict[str, Any]:
        # Check if key exists and update
        for mem in self.memories:
            if mem["key"].lower() == key.lower():
                mem["value"] = value
                mem["updated_at"] = datetime.now(timezone.utc).isoformat()
                return mem

        mem = {
            "id": f"mem_{uuid.uuid4().hex[:8]}",
            "category": category,
            "key": key,
            "value": value,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        self.memories.append(mem)
        return mem

    async def retrieve_memories(self, query: str) -> list[dict[str, Any]]:
        q_lower = query.lower().strip()
        matches = []
        for mem in self.memories:
            if q_lower in mem["key"].lower() or q_lower in mem["value"].lower() or q_lower in mem["category"].lower():
                matches.append(mem)
        return matches if matches else self.memories[:5]

memory_store = MemoryStore()
