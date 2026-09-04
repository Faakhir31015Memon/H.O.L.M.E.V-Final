from typing import Dict, Any, Optional

class ContextEngine:
    def __init__(self):
        self.active_room: str = "Bedroom"
        self.active_device: Optional[str] = None
        self.active_3d_object: Optional[str] = None
        self.active_circuit_id: Optional[str] = None
        self.active_user: str = "Boss"
        self.recent_messages: list = []

    def update_context(self, message: str, role: str = "user"):
        self.recent_messages.append({"role": role, "content": message})
        if len(self.recent_messages) > 10:
            self.recent_messages.pop(0)

    def get_full_context(self) -> Dict[str, Any]:
        return {
            "active_room": self.active_room,
            "active_device": self.active_device,
            "active_3d_object": self.active_3d_object,
            "active_circuit_id": self.active_circuit_id,
            "active_user": self.active_user,
            "recent_messages": self.recent_messages[-5:]
        }

context_engine = ContextEngine()
