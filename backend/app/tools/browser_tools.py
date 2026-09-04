import os
import webbrowser
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult

class OpenBrowserInput(BaseModel):
    url: str = Field(description="URL to open, e.g. https://www.google.com or https://www.youtube.com")

class BrowserOpenTool(BaseTool):
    name = "browser.open"
    description = "Opens a web browser and navigates to the specified URL."
    category = "browser"
    permission_level = 1
    input_schema = OpenBrowserInput

    async def _run(self, url: str) -> ToolResult:
        try:
            target_url = url if url.startswith("http") else f"https://{url}"
            webbrowser.open(target_url)
            if os.name == 'nt':
                os.system(f'start "" "{target_url}"')
            return ToolResult(
                success=True,
                verified=True,
                data={"url": target_url, "action": "browser_opened"},
                error=None
            )
        except Exception as e:
            return ToolResult(success=False, verified=False, error=str(e))
