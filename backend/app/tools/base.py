import time
import abc
from typing import Type, Dict, Any, Optional
from pydantic import BaseModel, Field

class ToolResult(BaseModel):
    success: bool
    verified: bool = False
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: int = 0
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class BaseTool(abc.ABC):
    name: str
    description: str
    version: str = "1.0.0"
    category: str = "general"
    permission_level: int = 1  # 0: Read-only, 1: Low-risk local, 2: Device/Comm, 3: Sensitive, 4: High risk
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel] = ToolResult
    timeout: int = 30
    retry_policy: Dict[str, Any] = {"max_retries": 1, "backoff_ms": 500}
    supports_cancellation: bool = True

    @abc.abstractmethod
    async def _run(self, **kwargs) -> ToolResult:
        """Internal execution logic implemented by subclasses."""
        pass

    async def execute(self, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            # Validate input using schema
            validated_input = self.input_schema(**kwargs)
            result = await self._run(**validated_input.model_dump())
            result.duration_ms = int((time.time() - start_time) * 1000)
            return result
        except Exception as e:
            duration = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=False,
                verified=False,
                data=None,
                error=str(e),
                duration_ms=duration
            )

    async def health_check(self) -> bool:
        return True

    def audit_metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "permission_level": self.permission_level,
            "version": self.version
        }
