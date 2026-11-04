"""Opening a browser is observable, so report exactly what was observed.

The previous version called `webbrowser.open(url)` and then, on Windows, also ran
`subprocess.Popen(f'start "" "{url}"', shell=True)`. That opened the page twice, put
a caller-supplied string into a shell command line (a `"` in the URL breaks out of the
quoting), and still returned `verified=True` for an action nothing checked.

Now: one call, no shell, http/https only, and the boolean the OS actually gave back.
"""

import webbrowser
from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolResult


class OpenBrowserInput(BaseModel):
    url: str = Field(description="URL to open, e.g. https://www.google.com or https://www.youtube.com")


class BrowserOpenTool(BaseTool):
    name = "browser.open"
    description = "Hands an http/https URL to the machine's default browser."
    category = "browser"
    permission_level = 1
    input_schema = OpenBrowserInput

    async def _run(self, url: str = "", **kwargs: Any) -> ToolResult:
        target = (url or "").strip()
        if not target:
            return ToolResult(success=False, verified=False, error="no URL was given", data={"opened": False})
        if not target.lower().startswith(("http://", "https://")):
            target = f"https://{target.lstrip('/')}"

        handed_off = webbrowser.open(target)
        return ToolResult(
            success=bool(handed_off),
            verified=False,
            data={
                "url": target,
                "handed_to_default_browser": bool(handed_off),
                "note": "the OS accepted the request; whether a window is showing was not observed",
            },
            error=None if handed_off else "no default browser accepted the URL from this process",
        )
