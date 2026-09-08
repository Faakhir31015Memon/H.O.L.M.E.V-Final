from typing import Dict, Optional, List
from app.tools.base import BaseTool
from app.tools.desktop_tools import OpenApplicationTool, CreateFolderTool, TypeTextTool, SystemControlTool
from app.tools.home_tools import HomeDeviceControlTool, CCTVDisplayTool, IRLearnTool
from app.tools.web_tools import WebSearchTool
from app.tools.browser_tools import BrowserOpenTool
from app.tools.threed_tools import Create3DObjectTool, Transform3DObjectTool
from app.tools.circuit_tools import CreateCircuitTool, SimulateCircuitTool
from app.tools.memory_tools import MemoryStoreTool, MemoryRetrieveTool
from app.tools.navigation_tools import NavigationRouteTool
from app.tools.mobile_tools import WhatsAppMessageTool, PhoneCallTool, SendEmailTool, MobileDisplayImageTool

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
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

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        return self._tools.get(tool_name)

    def list_tools(self) -> List[Dict[str, str]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "permission_level": str(tool.permission_level)
            }
            for tool in self._tools.values()
        ]

tool_registry = ToolRegistry()
