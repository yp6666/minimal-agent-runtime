from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from minimal_agent.models import ToolResult


class AgentTool(ABC):
    name: str
    description: str
    args_model: type[BaseModel]

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def validate(self, arguments: dict[str, Any]) -> BaseModel:
        return self.args_model.model_validate(arguments)

    async def safe_execute(
        self, arguments: dict[str, Any], *, session_id: str
    ) -> ToolResult:
        try:
            validated = self.validate(arguments)
        except ValidationError as error:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="INVALID_ARGUMENTS",
                message=error.errors(include_url=False).__str__(),
            )

        try:
            return await self.execute(validated, session_id=session_id)
        except Exception as error:  # Runtime boundary: tools must not crash the loop.
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="TOOL_EXECUTION_ERROR",
                message=str(error)[:500],
            )

    @abstractmethod
    async def execute(self, arguments: BaseModel, *, session_id: str) -> ToolResult:
        raise NotImplementedError
