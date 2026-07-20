from __future__ import annotations

from typing import Any

from minimal_agent.models import ToolResult

from .base import AgentTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> AgentTool:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    async def execute(
        self, name: str, arguments: dict[str, Any], *, session_id: str
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                tool_name=name,
                error_code="UNKNOWN_TOOL",
                message=f"工具不存在：{name}",
            )
        return await tool.safe_execute(arguments, session_id=session_id)
