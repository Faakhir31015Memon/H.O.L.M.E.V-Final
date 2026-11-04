"""Tools describe the world they touched, and nothing they did not.

These pin the fixes for the last self-graded claims in the tool layer: a memory
store that was really a process-local list, a retriever that padded a no-match with
unrelated facts, a browser opener that put a URL into a shell command, and a circuit
tool that accepted "parallel" while building an LED loop.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.engines.memory import memory_engine
from app.tools import web_tools
from app.tools.base import ToolResult
from app.tools.browser_tools import BrowserOpenTool
from app.tools.circuit_tools import CreateCircuitTool, SimulateCircuitTool
from app.tools.memory_tools import MemoryRetrieveTool, MemoryStoreTool
from app.tools.web_tools import WebSearchTool

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"


def _verified_true_lines(module: Path) -> list[int]:
    """Lines where a tool literal-grades its own work, ignoring prose that mentions it."""

    tree = ast.parse(module.read_text(encoding="utf-8"))
    return [
        call.lineno
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call))
        for kw in call.keywords
        if kw.arg == "verified" and isinstance(kw.value, ast.Constant) and kw.value.value is True
    ]


def test_no_tool_awards_itself_verified():
    """`verified` is the verification engine's to grant; a tool grading its own work proves nothing."""

    offenders = [
        f"{module.name}:{line}" for module in sorted(TOOLS_DIR.glob("*.py")) for line in _verified_true_lines(module)
    ]
    assert offenders == [], f"tools may not self-verify, but these do: {offenders}"


async def test_memory_store_really_writes_a_row_and_waits_for_confirmation():
    result = await MemoryStoreTool().execute(category="preference", key="tea", value="chai with less sugar")

    assert result.success is True
    assert result.verified is False, "the tool wrote a row; the user has not confirmed it yet"
    assert result.data["stored"] is True
    assert result.data["state"] == "pending"
    assert "confirm" in result.data["confirm_with"]

    pending = await memory_engine.list_memories(state="pending", limit=50)
    assert any(record.key.endswith("tea") for record in pending), "it is a database row, not a list in RAM"


async def test_a_secret_is_refused_before_it_reaches_the_table():
    result = await MemoryStoreTool().execute(category="fact", key="wifi_password", value="hunter2verysecret")

    assert result.success is False
    assert result.data["stored"] is False
    assert "protected" in (result.error or "").lower() or "credential" in (result.error or "").lower()
    assert await memory_engine.list_memories(state=None, limit=50) == []


async def test_retrieval_stays_empty_instead_of_padding_with_unrelated_facts():
    await MemoryStoreTool().execute(category="preference", key="tea", value="chai with less sugar")

    empty = await MemoryRetrieveTool().execute(query="garden gnome")
    assert empty.success is True
    assert empty.data["memories"] == [], "the old store answered a no-match with the first five memories"
    assert empty.data["match_count"] == 0

    # a pending memory is not used until the user confirms it
    pending_only = await MemoryRetrieveTool().execute(query="tea chai sugar")
    assert pending_only.data["memories"] == []

    recorded = await memory_engine.list_memories(state="pending", limit=10)
    await memory_engine.confirm(recorded[0].id)

    after = await MemoryRetrieveTool().execute(query="tea chai sugar")
    assert after.data["match_count"] == 1
    assert after.data["memories"][0]["state"] == "active"


async def test_browser_open_forces_a_scheme_and_never_touches_a_shell(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("app.tools.browser_tools.webbrowser.open", lambda url: opened.append(url) or True)

    result = await BrowserOpenTool().execute(url='youtube.com/watch" &calc')

    assert result.success is True
    assert opened[0].startswith("https://")
    assert result.data["handed_to_default_browser"] is True
    assert result.verified is False, "handing a URL to the OS is not the same as seeing the page"

    tree = ast.parse((TOOLS_DIR / "browser_tools.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "subprocess" not in imported, "a URL must never be interpolated into a command line"

    shell_arguments = [
        kw for node in ast.walk(tree) if isinstance(node, ast.Call) for kw in node.keywords if kw.arg == "shell"
    ]
    assert not shell_arguments, "no shell= keyword anywhere in the browser tool"


async def test_circuit_create_refuses_a_topology_it_cannot_build():
    result = await CreateCircuitTool().execute(circuit_type="parallel")

    assert result.success is False
    assert result.data["created"] is False
    assert "series loop" in (result.error or "")
    assert result.data["supported"] == ["led", "series"]


async def test_circuit_create_uses_the_numbers_it_was_given():
    built = await CreateCircuitTool().execute(circuit_type="led", battery_voltage=5.0, resistance=100.0)
    assert built.success is True and built.verified is False

    simulated = await SimulateCircuitTool().execute()
    assert simulated.data["status"] == "NORMAL_OPERATION"
    # (5V - 2V LED drop) / 100 ohm = 30 mA
    assert simulated.data["current_ma"] == pytest.approx(30.0, abs=0.1)


async def test_simulating_an_empty_circuit_says_open_circuit():
    from app.circuits.simulator import circuit_simulator

    circuit_simulator.components.clear()
    circuit_simulator.connections.clear()

    result = await SimulateCircuitTool().execute()
    assert result.success is False
    assert result.data["status"] == "OPEN_CIRCUIT"
    assert result.data["current_ma"] == 0.0


class _NoResultsResponse:
    status_code = 200
    text = "<html><body>nothing matched on this page</body></html>"


async def test_web_search_reports_zero_results_as_zero(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _NoResultsResponse()

    monkeypatch.setattr(web_tools.httpx, "AsyncClient", FakeClient)

    result = await WebSearchTool().execute(query="anything")
    assert result.success is True
    assert result.verified is False, "page text from strangers is not a verified fact"
    assert result.data["snippets"] == [] and result.data["result_count"] == 0
    assert result.data["source"] == "html.duckduckgo.com"


async def test_a_web_search_that_cannot_reach_the_page_is_a_failure(monkeypatch):
    class BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            raise web_tools.httpx.ConnectError("no route to host")

    monkeypatch.setattr(web_tools.httpx, "AsyncClient", BrokenClient)

    result: ToolResult = await WebSearchTool().execute(query="anything")
    assert result.success is False and result.verified is False
