
from app.providers.base import ToolSpec
from app.tools.base import BaseTool
from app.tools.browser_tools import BrowserOpenTool
from app.tools.circuit_tools import CreateCircuitTool, SimulateCircuitTool
from app.tools.desktop_tools import CreateFolderTool, OpenApplicationTool, SystemControlTool, TypeTextTool
from app.tools.home_tools import CCTVDisplayTool, HomeDeviceControlTool, IRLearnTool
from app.tools.memory_tools import MemoryRetrieveTool, MemoryStoreTool
from app.tools.mobile_tools import MobileDisplayImageTool, PhoneCallTool, SendEmailTool, WhatsAppMessageTool
from app.tools.navigation_tools import NavigationRouteTool
from app.tools.threed_tools import (
    Create3DObjectTool,
    Delete3DObjectTool,
    Export3DModelTool,
    Read3DSceneTool,
    SendToDisplayTool,
    Transform3DObjectTool,
)
from app.tools.web_tools import WebSearchTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self.register_default_tools()

    def register_tool(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def register_default_tools(self):
        default_tools = [
            OpenApplicationTool(),
            CreateFolderTool(),
            TypeTextTool(),
            SystemControlTool(),
            HomeDeviceControlTool(),
            CCTVDisplayTool(),
            IRLearnTool(),
            WebSearchTool(),
            BrowserOpenTool(),
            Create3DObjectTool(),
            Transform3DObjectTool(),
            Delete3DObjectTool(),
            Read3DSceneTool(),
            Export3DModelTool(),
            SendToDisplayTool(),
            CreateCircuitTool(),
            SimulateCircuitTool(),
            MemoryStoreTool(),
            MemoryRetrieveTool(),
            NavigationRouteTool(),
            WhatsAppMessageTool(),
            PhoneCallTool(),
            SendEmailTool(),
            MobileDisplayImageTool()
        ]
        for t in default_tools:
            self.register_tool(t)

    def get_tool(self, tool_name: str) -> BaseTool | None:
        return self._tools.get(tool_name)

    def list_tools(self) -> list[dict[str, str]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "permission_level": str(tool.permission_level)
            }
            for tool in self._tools.values()
        ]

    def describe_all(self) -> dict[str, ToolSpec]:
        """Rich, model-readable catalog including each tool's real input schema."""

        specs: dict[str, ToolSpec] = {}
        for tool in self._tools.values():
            try:
                parameters = tool.input_schema.model_json_schema()
            except Exception:
                parameters = {"type": "object", "properties": {}}
            specs[tool.name] = ToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=parameters,
                permission_level=tool.permission_level,
            )
        return specs

    def permission_level_of(self, tool_name: str) -> int | None:
        """The authoritative level, always taken from the tool - never from the model."""

        tool = self._tools.get(tool_name)
        return tool.permission_level if tool else None

    def tool_names(self) -> list[str]:
        return sorted(self._tools)


tool_registry = ToolRegistry()
