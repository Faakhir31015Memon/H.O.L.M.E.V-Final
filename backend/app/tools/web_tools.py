from typing import Any
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult

class WebSearchInput(BaseModel):
    query: str = Field(description="Search query string")

class WebSearchTool(BaseTool):
    name = "web.search"
    description = "Searches the live web for up-to-date information, news, weather, or facts."
    category = "web"
    permission_level = 0
    input_schema = WebSearchInput

    async def _run(self, query: str, **kwargs: Any) -> ToolResult:
        try:
            # Live web search using DuckDuckGo HTML endpoint
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                )
                if resp.status_code != 200:
                    return ToolResult(success=False, verified=False, error=f"Search HTTP status {resp.status_code}")

                soup = BeautifulSoup(resp.text, "html.parser")
                results = []
                for result in soup.find_all("a", class_="result__snippet", limit=5):
                    results.append(result.get_text(strip=True))

                return ToolResult(
                    success=True,
                    verified=True,
                    data={"query": query, "snippets": results},
                    error=None
                )
        except Exception as e:
            return ToolResult(success=False, verified=False, error=str(e))
