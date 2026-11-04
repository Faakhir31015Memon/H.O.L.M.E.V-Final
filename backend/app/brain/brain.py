"""A thin facade over the orchestrator, kept for callers that want one call.

The old version of this file picked a tool with keywords and then spoke a
sentence from a template table, so the assistant sounded confident about actions
it had not taken. Everything about what to do, whether it worked, and how to say
so now belongs to the engines behind `orchestrator.run()`; this module only
adapts that outcome into the shape the voice pipeline already expects.
"""

from __future__ import annotations

from typing import Any

from app.brain.orchestrator import orchestrator


class HolmevBrain:
    async def process_user_request(
        self,
        user_input: str,
        session_id: str = "default_session",
        user_emotion: str | None = None,
    ) -> dict[str, Any]:
        outcome = await orchestrator.run(
            user_input, session_id=session_id, emotion=(user_emotion or "").lower() or None
        )
        recorded = outcome.as_dict()
        recorded["spoken_response"] = outcome.reply.text
        return recorded


holmev_brain = HolmevBrain()
