from __future__ import annotations

from .models import AgentAction, LLMMessage


class OutputParser:
    """Turns a provider response into one of the runtime's two legal actions."""

    def parse(self, message: LLMMessage) -> AgentAction:
        rationale = self._brief(message.reasoning_content or message.content)
        if message.tool_calls:
            return AgentAction(
                type="tool_calls",
                tool_calls=message.tool_calls,
                brief_rationale=rationale,
            )
        answer = (message.content or "").strip()
        if not answer:
            raise ValueError("模型既没有返回工具调用，也没有返回最终答案")
        return AgentAction(
            type="final", answer=answer, brief_rationale=rationale
        )

    @staticmethod
    def _brief(value: str | None) -> str | None:
        if not value:
            return None
        return " ".join(value.split())[:240]
