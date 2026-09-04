import uuid
from typing import Dict, Any, List, Optional

class ThreeDManager:
    def __init__(self):
        self.objects: Dict[str, Dict[str, Any]] = {}
        self.selected_object_id: Optional[str] = None

    def create_object(self, object_type: str, position: List[float], color: str) -> Dict[str, Any]:
        obj_id = f"obj_{uuid.uuid4().hex[:8]}"
        obj_data = {
            "id": obj_id,
            "type": object_type,
            "position": position,
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1],
            "color": color
        }
        self.objects[obj_id] = obj_data
        self.selected_object_id = obj_id
        return obj_data

    def transform_object(
        self, object_id: Optional[str], position: Optional[List[float]], scale: Optional[List[float]]
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        target_id = object_id or self.selected_object_id
        if not target_id or target_id not in self.objects:
            # If no object exists yet, create default cube first
            if not self.objects:
                obj = self.create_object("cube", [0, 0, 0], "#00f0ff")
                target_id = obj["id"]
            else:
                target_id = list(self.objects.keys())[-1]

        obj = self.objects[target_id]
        if position:
            obj["position"] = [obj["position"][i] + position[i] for i in range(3)]
        if scale:
            obj["scale"] = [obj["scale"][i] * scale[i] for i in range(3)]
        return obj, None

    def get_scene(self) -> List[Dict[str, Any]]:
        return list(self.objects.values())

threed_manager = ThreeDManager()
