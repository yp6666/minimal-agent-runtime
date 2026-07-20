from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from minimal_agent.models import ToolResult
from minimal_agent.storage import SQLiteStore

from .base import AgentTool


class TodoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create", "list", "complete"] = Field(
        description="create 创建、list 查看、complete 完成待办"
    )
    title: str | None = Field(default=None, max_length=300)
    due_date: str | None = Field(default=None, description="YYYY-MM-DD，可为空")
    item_id: int | None = Field(
        default=None,
        ge=1,
        description="当前会话中的待办编号，从 1 开始",
    )


class TodoTool(AgentTool):
    name = "todo"
    description = (
        "在当前会话中创建、查看或完成待办。"
        "不同会话的待办相互隔离，编号在每个会话内都从 1 开始。"
    )
    args_model = TodoArgs

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def execute(self, arguments: TodoArgs, *, session_id: str) -> ToolResult:
        if arguments.action == "list":
            return ToolResult(
                ok=True,
                tool_name=self.name,
                data={"items": self.store.list_todos(session_id)},
            )

        if arguments.action == "create":
            if not arguments.title or not arguments.title.strip():
                return ToolResult(
                    ok=False,
                    tool_name=self.name,
                    error_code="TITLE_REQUIRED",
                    message="创建待办时必须提供 title",
                )
            item = self.store.create_todo(
                session_id, arguments.title.strip(), arguments.due_date
            )
            return ToolResult(ok=True, tool_name=self.name, data={"item": item})

        if arguments.item_id is None:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="ITEM_ID_REQUIRED",
                message="完成待办时必须提供 item_id",
            )
        item = self.store.complete_todo(session_id, arguments.item_id)
        if item is None:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="TODO_NOT_FOUND",
                message="当前会话中没有这个待办",
            )
        return ToolResult(ok=True, tool_name=self.name, data={"item": item})
