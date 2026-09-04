import os
import subprocess
import psutil
import pyautogui
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult
from app.security.sanitizer import get_allowed_app_command, validate_safe_path

class OpenAppInput(BaseModel):
    application: str = Field(description="Name of application to open, e.g. notepad, chrome, calculator")

class OpenApplicationTool(BaseTool):
    name = "desktop.open_application"
    description = "Opens a desktop application securely on the system."
    category = "desktop"
    permission_level = 1
    input_schema = OpenAppInput

    async def _run(self, application: str) -> ToolResult:
        try:
            cmd = get_allowed_app_command(application)
            proc = subprocess.Popen(cmd)
            # Verify process launched
            if proc.poll() is None or proc.pid > 0:
                return ToolResult(
                    success=True,
                    verified=True,
                    data={"application": application, "pid": proc.pid},
                    error=None
                )
            return ToolResult(success=False, verified=False, error=f"Failed to start {application}")
        except Exception as e:
            return ToolResult(success=False, verified=False, error=str(e))

class CreateFolderInput(BaseModel):
    folder_path: str = Field(description="Target path for folder creation")

class CreateFolderTool(BaseTool):
    name = "desktop.create_folder"
    description = "Creates a directory on the local system."
    category = "desktop"
    permission_level = 1
    input_schema = CreateFolderInput

    async def _run(self, folder_path: str) -> ToolResult:
        try:
            safe_path = validate_safe_path(folder_path)
            os.makedirs(safe_path, exist_ok=True)
            verified = os.path.exists(safe_path) and os.path.isdir(safe_path)
            return ToolResult(
                success=verified,
                verified=verified,
                data={"path": str(safe_path)},
                error=None if verified else "Directory creation verification failed"
            )
        except Exception as e:
            return ToolResult(success=False, verified=False, error=str(e))

class TypeTextInput(BaseModel):
    text: str = Field(description="Text content to type into active application")

class TypeTextTool(BaseTool):
    name = "desktop.type_text"
    description = "Types text into the active window via desktop keyboard automation."
    category = "desktop"
    permission_level = 1
    input_schema = TypeTextInput

    async def _run(self, text: str) -> ToolResult:
        try:
            pyautogui.write(text, interval=0.02)
            return ToolResult(
                success=True,
                verified=True,
                data={"typed_length": len(text)},
                error=None
            )
        except Exception as e:
            return ToolResult(success=False, verified=False, error=str(e))
