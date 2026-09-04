from typing import Dict, Any, Optional
from pydantic import BaseModel
from app.tools.base import BaseTool

class PermissionCheckResult(BaseModel):
    allowed: bool
    requires_user_approval: bool = False
    reason: str = "Authorized"

class PermissionEngine:
    def __init__(self, policy_mode: str = "ask_for_risky"):
        self.policy_mode = policy_mode
        self._tool_permission_overrides: Dict[str, int] = {}
        self._session_authorizations: set = set()

    def set_tool_level(self, tool_name: str, level: int):
        self._tool_permission_overrides[tool_name] = level

    def authorize_session_tool(self, tool_name: str):
        self._session_authorizations.add(tool_name)

    def evaluate(self, tool: BaseTool, arguments: Dict[str, Any], user_is_admin: bool = False) -> PermissionCheckResult:
        level = self._tool_permission_overrides.get(tool.name, tool.permission_level)
        
        # Level 4: Blocked by default unless admin explicit session authorization
        if level >= 4 and not user_is_admin:
            return PermissionCheckResult(
                allowed=False,
                requires_user_approval=False,
                reason=f"Tool '{tool.name}' is Level 4 (Highly Sensitive) and restricted."
            )
            
        if tool.name in self._session_authorizations:
            return PermissionCheckResult(allowed=True, requires_user_approval=False, reason="Session authorized.")

        # Level 0 (Read-only) always allowed
        if level == 0:
            return PermissionCheckResult(allowed=True, requires_user_approval=False, reason="Level 0 Read-only action.")

        # Level 1 (Low risk local)
        if level == 1:
            if self.policy_mode == "always_ask":
                return PermissionCheckResult(allowed=True, requires_user_approval=True, reason="Always ask policy active.")
            return PermissionCheckResult(allowed=True, requires_user_approval=False, reason="Level 1 action auto-approved.")

        # Level 2 & 3 (Medium / Destructive risk)
        if level >= 2:
            if user_is_admin and self.policy_mode == "auto_approve_low":
                return PermissionCheckResult(allowed=True, requires_user_approval=False, reason="Admin auto-approved.")
            return PermissionCheckResult(
                allowed=True,
                requires_user_approval=True,
                reason=f"Level {level} action requires confirmation."
            )

        return PermissionCheckResult(allowed=True, requires_user_approval=False)

permission_engine = PermissionEngine()
