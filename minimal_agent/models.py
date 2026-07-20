from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMMessage(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning_content: str | None = None


@dataclass(slots=True)
class AgentAction:
    type: Literal["tool_calls", "final"]
    answer: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    brief_rationale: str | None = None


class ToolResult(BaseModel):
    ok: bool
    tool_name: str
    data: dict[str, Any] | None = None
    error_code: str | None = None
    message: str | None = None


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    title: str = Field(default="新会话", min_length=1, max_length=100)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=10_000)


class TodoView(BaseModel):
    id: int
    session_id: str
    title: str
    status: str
    due_date: str | None = None
    created_at: str


class AgentRunResult(BaseModel):
    run_id: str
    answer: str
    steps: int
    stopped_by_limit: bool = False
