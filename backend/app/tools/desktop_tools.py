"""Host-control tools: they do a real thing or they say that they did not.

Three rules hold this file together:

* no program may be launched unless it is on the sanitizer's allowlist;
* paths go through the workspace guard, so a model-authored `~/.ssh/...` is refused;
* `verified` is never set here - the verification engine decides that later.

The previous version reported `verified=True` for a `Popen` that only proves a
command was handed to the OS, and claimed a shutdown was "initiated successfully"
while issuing nothing. Both are gone.
"""

import os
import subprocess
from typing import Any

try:
    import pyautogui  # type: ignore
except ImportError:
    pyautogui = None

from pydantic import BaseModel, Field

from app.config.settings import settings
from app.security.sanitizer import get_allowed_app_command, validate_safe_path
from app.tools.base import BaseTool, ToolResult


class OpenAppInput(BaseModel):
    application: str = Field(description="Name of application to open, e.g. notepad, chrome, calculator")


class OpenApplicationTool(BaseTool):
    name = "desktop.open_application"
    description = "Launches an allowlisted desktop application on this machine."
    category = "desktop"
    permission_level = 2
    input_schema = OpenAppInput

    async def _run(self, application: str = "", **kwargs: Any) -> ToolResult:
        try:
            executable = get_allowed_app_command(application)[0]
        except ValueError as exc:
            return ToolResult(success=False, verified=False, error=str(exc))

        try:
            if os.name == "nt":
                # ShellExecute searches PATH, so no shell string is built from the input.
                os.startfile(executable)  # type: ignore[attr-defined]
            else:
                subprocess.Popen([executable])
        except Exception as exc:
            return ToolResult(
                success=False,
                verified=False,
                error=f"{executable} was not launched: {type(exc).__name__}: {exc}"[:300],
            )

        return ToolResult(
            success=True,
            verified=False,
            data={
                "application": executable,
                "launch_attempted": True,
                "note": "the OS accepted the launch; whether a window appeared is a separate check",
            },
        )


class CreateFolderInput(BaseModel):
    folder_path: str = Field(description="Folder path inside the H.O.L.M.E.V workspace")


class CreateFolderTool(BaseTool):
    name = "desktop.create_folder"
    description = "Creates a directory inside the workspace root."
    category = "desktop"
    permission_level = 1
    input_schema = CreateFolderInput

    async def _run(self, folder_path: str = "", **kwargs: Any) -> ToolResult:
        try:
            safe_path = validate_safe_path(folder_path)
        except PermissionError as exc:
            return ToolResult(success=False, verified=False, error=str(exc))

        try:
            existed = safe_path.exists()
            os.makedirs(safe_path, exist_ok=True)
        except OSError as exc:
            return ToolResult(success=False, verified=False, error=f"could not create '{folder_path}': {exc}")

        return ToolResult(success=True, verified=False, data={"path": str(safe_path), "already_existed": existed})


class TypeTextInput(BaseModel):
    text: str = Field(description="Text content to type into the focused window")


class TypeTextTool(BaseTool):
    name = "desktop.type_text"
    description = "Types text into whichever window currently has keyboard focus."
    category = "desktop"
    permission_level = 3
    input_schema = TypeTextInput

    async def _run(self, text: str = "", **kwargs: Any) -> ToolResult:
        if pyautogui is None:
            return ToolResult(
                success=False, verified=False, error="keyboard automation is unavailable here: pip install pyautogui"
            )
        try:
            pyautogui.write(text, interval=0.02)
        except Exception as exc:
            return ToolResult(success=False, verified=False, error=f"typing failed: {exc}"[:300])

        return ToolResult(
            success=True,
            verified=False,
            data={"typed_length": len(text)},
            metadata={"warning": "this typed into the focused window, whatever that was"},
        )


class SystemControlInput(BaseModel):
    action: str = Field(description="System action: shutdown, restart, sleep, lock")


class SystemControlTool(BaseTool):
    name = "desktop.system_control"
    description = "Requests a host power action. Disabled unless ALLOW_SYSTEM_POWER_ACTIONS is set."
    category = "desktop"
    permission_level = 4
    input_schema = SystemControlInput

    async def _run(self, action: str = "shutdown", **kwargs: Any) -> ToolResult:
        action_clean = action.lower().strip()
        if action_clean not in {"shutdown", "restart", "sleep", "lock"}:
            return ToolResult(success=False, verified=False, error=f"unknown system action '{action_clean}'")

        if not settings.ALLOW_SYSTEM_POWER_ACTIONS:
            return ToolResult(
                success=False,
                verified=False,
                error=(
                    f"'{action_clean}' was NOT issued. Power actions are off by default because a wrong one "
                    "costs your unsaved work; set ALLOW_SYSTEM_POWER_ACTIONS=true in .env to enable them."
                ),
                data={"action": action_clean, "performed": False},
            )

        command = _power_command(action_clean)
        if command is None:
            return ToolResult(
                success=False, verified=False, error=f"no power command is known for '{action_clean}' on this OS"
            )

        result = subprocess.run(command, shell=False, capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0:
            return ToolResult(
                success=False,
                verified=False,
                error=f"'{action_clean}' refused by the OS: {(result.stderr or result.stdout).strip()[:200]}",
            )

        return ToolResult(
            success=True,
            verified=False,
            data={"action": action_clean, "performed": True, "abortable": action_clean in {"shutdown", "restart"}},
        )


def _power_command(action: str) -> list[str] | None:
    if os.name == "nt":
        return {
            "shutdown": ["shutdown", "/s", "/t", "15"],
            "restart": ["shutdown", "/r", "/t", "15"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        }.get(action)
    return {
        "shutdown": ["shutdown", "-h", "+0"],
        "restart": ["shutdown", "-r", "+0"],
        "sleep": ["systemctl", "suspend"],
        "lock": ["xdg-screensaver", "lock"],
    }.get(action)
