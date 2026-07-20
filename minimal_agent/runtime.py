from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from typing import Any

from .context import ContextManager
from .llm import LLMClient, LLMError
from .models import AgentRunResult, ToolCall
from .parser import OutputParser
from .storage import SQLiteStore
from .tools.registry import ToolRegistry


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        store: SQLiteStore,
        context: ContextManager,
        *,
        max_steps: int = 6,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.store = store
        self.context = context
        self.max_steps = max_steps
        self.parser = OutputParser()
        self._session_locks: defaultdict[str, asyncio.Lock] = defaultdict(
            asyncio.Lock
        )

    async def run(self, session_id: str, user_input: str) -> AgentRunResult:
        if not user_input.strip():
            raise ValueError("用户输入不能为空")
        self.store.get_session(session_id)
        async with self._session_locks[session_id]:
            return await self._run_locked(session_id, user_input.strip())

    async def _run_locked(
        self, session_id: str, user_input: str
    ) -> AgentRunResult:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        self.store.append_message(session_id, "user", user_input)
        self.store.add_trace(
            session_id, run_id, 0, "run_started", {"input": user_input[:500]}
        )

        for step in range(1, self.max_steps + 1):
            messages = self.context.build(session_id)
            started = time.perf_counter()
            try:
                llm_message = await self.llm.complete(
                    messages, self.registry.schemas()
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                action = self.parser.parse(llm_message)
            except (LLMError, ValueError) as error:
                duration_ms = int((time.perf_counter() - started) * 1000)
                self.store.add_trace(
                    session_id,
                    run_id,
                    step,
                    "llm_error",
                    {"error": str(error)},
                    duration_ms,
                )
                answer = f"本次运行未完成：{error}"
                self.store.append_message(session_id, "assistant", answer)
                return AgentRunResult(run_id=run_id, answer=answer, steps=step)

            if action.type == "final":
                answer = action.answer or "任务已完成。"
                self.store.add_trace(
                    session_id,
                    run_id,
                    step,
                    "final_answer",
                    {
                        "answer": answer[:1000],
                        "brief_rationale": action.brief_rationale,
                    },
                    duration_ms,
                )
                self.store.append_message(session_id, "assistant", answer)
                return AgentRunResult(
                    run_id=run_id, answer=answer, steps=step
                )

            serialized_calls = [self._serialize_call(call) for call in action.tool_calls]
            self.store.append_message(
                session_id,
                "assistant",
                llm_message.content,
                tool_calls=serialized_calls,
            )
            self.store.add_trace(
                session_id,
                run_id,
                step,
                "llm_tool_decision",
                {
                    "calls": serialized_calls,
                    "brief_rationale": action.brief_rationale,
                },
                duration_ms,
            )

            for call in action.tool_calls:
                tool_started = time.perf_counter()
                result = await self.registry.execute(
                    call.name, call.arguments, session_id=session_id
                )
                tool_duration_ms = int((time.perf_counter() - tool_started) * 1000)
                result_json = result.model_dump_json(exclude_none=True)
                self.store.append_message(
                    session_id,
                    "tool",
                    result_json,
                    tool_call_id=call.id,
                )
                self.store.add_trace(
                    session_id,
                    run_id,
                    step,
                    "tool_finished",
                    {
                        "tool_call_id": call.id,
                        "tool_name": call.name,
                        "arguments": call.arguments,
                        "result": json.loads(result_json),
                    },
                    tool_duration_ms,
                )

        answer = (
            f"为了避免无限循环，本次运行在 {self.max_steps} 个步骤后停止。"
            "你可以换一种说法继续让我处理。"
        )
        self.store.append_message(session_id, "assistant", answer)
        self.store.add_trace(
            session_id,
            run_id,
            self.max_steps,
            "step_limit_reached",
            {"max_steps": self.max_steps},
        )
        return AgentRunResult(
            run_id=run_id,
            answer=answer,
            steps=self.max_steps,
            stopped_by_limit=True,
        )

    @staticmethod
    def _serialize_call(call: ToolCall) -> dict[str, Any]:
        return {"id": call.id, "name": call.name, "arguments": call.arguments}
