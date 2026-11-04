import re
from pathlib import Path

from app.security.path_guard import PathRejected, guard, workspace_root

ALLOWED_APPS = {
    "chrome": ["chrome", "google-chrome", "chrome.exe"],
    "notepad": ["notepad", "notepad.exe"],
    "calculator": ["calc", "calculator.exe"],
    "explorer": ["explorer", "explorer.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["cmd.exe", "wt.exe", "powershell.exe"]
}

def validate_safe_path(target_path: str) -> Path:
    """Confine a tool's path to the workspace root, using the one guard the brain trusts.

    The previous version here fell back to "anything inside the user profile is
    fine", which made ~/.ssh a legal target for a model-authored path.
    """

    try:
        return guard(target_path, root=workspace_root()).resolved
    except PathRejected as exc:
        raise PermissionError(f"Path access denied: {target_path} - {exc.reason}") from exc

def sanitize_input(text: str) -> str:
    """Removes unsafe control characters."""
    if not text:
        return ""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

def get_allowed_app_command(app_name: str) -> list[str]:
    """Only names on the allowlist may be launched.

    The old fallback ran *any* alphanumeric string the model produced as a
    program, which made "open whatever I say" a legal instruction.
    """

    app_lower = app_name.lower().strip()
    for key, cmds in ALLOWED_APPS.items():
        if key in app_lower or app_lower in key:
            return cmds
    raise ValueError(
        f"Application '{app_name}' is not in the allowed policy list. "
        f"Allowed: {', '.join(sorted(ALLOWED_APPS))}."
    )
