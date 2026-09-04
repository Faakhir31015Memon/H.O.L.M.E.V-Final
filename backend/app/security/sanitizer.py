import os
import re
from pathlib import Path
from typing import List

ALLOWED_APPS = {
    "chrome": ["chrome", "google-chrome", "chrome.exe"],
    "notepad": ["notepad", "notepad.exe"],
    "calculator": ["calc", "calculator.exe"],
    "explorer": ["explorer", "explorer.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["cmd.exe", "wt.exe", "powershell.exe"]
}

SAFE_BASE_DIR = Path(os.getcwd()).resolve()

def validate_safe_path(target_path: str, allow_outside: bool = False) -> Path:
    """Ensures file paths prevent directory traversal attacks."""
    resolved = Path(target_path).resolve()
    if not allow_outside:
        try:
            resolved.relative_to(SAFE_BASE_DIR)
        except ValueError:
            # If path is inside user profile/desktop, also permit
            user_profile = Path(os.path.expanduser("~")).resolve()
            try:
                resolved.relative_to(user_profile)
            except ValueError:
                raise PermissionError(f"Path access denied: {target_path} is outside allowed boundaries.")
    return resolved

def sanitize_input(text: str) -> str:
    """Removes unsafe control characters."""
    if not text:
        return ""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

def get_allowed_app_command(app_name: str) -> List[str]:
    app_lower = app_name.lower().strip()
    for key, cmds in ALLOWED_APPS.items():
        if key in app_lower or app_lower in key:
            return cmds
    # Default fallback to app_name if simple alphanumeric
    if re.match(r'^[a-zA-Z0-9_\-\.]+$', app_name):
        return [app_name]
    raise ValueError(f"Application '{app_name}' is not in the allowed policy list.")
