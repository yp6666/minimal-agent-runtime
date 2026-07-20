from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .models import LLMMessage, ToolCall


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    @abstractmethod
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMMessage:
        raise NotImplementedError


class DeepSeekClient(LLMClient):
    """Small OpenAI-compatible client; it deliberately contains no agent logic."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMMessage:
        if not self.api_key:
            raise LLMError("缺少 DEEPSEEK_API_KEY，请先配置 minimal_agent/.env")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 2048,
            # The runtime needs reliable tool decisions, not a verbose hidden chain.
            "thinking": {"type": "disabled"},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            if self.client is not None:
                response = await self._request(self.client, payload)
            else:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await self._request(client, payload)
            return self._parse_response(response.json())
        except httpx.TimeoutException as error:
            raise LLMError("DeepSeek 请求超时") from error
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:400]
            raise LLMError(
                f"DeepSeek 返回 HTTP {error.response.status_code}: {detail}"
            ) from error
        except httpx.RequestError as error:
            raise LLMError(f"无法连接 DeepSeek：{type(error).__name__}") from error
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LLMError("DeepSeek 返回格式无法解析") from error

    async def _request(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> httpx.Response:
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> LLMMessage:
        message = data["choices"][0]["message"]
        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            if isinstance(raw_arguments, str):
                arguments = json.loads(raw_arguments)
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                raise ValueError("Tool arguments must be JSON")
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            calls.append(
                ToolCall(
                    id=str(raw["id"]),
                    name=str(function["name"]),
                    arguments=arguments,
                )
            )
        return LLMMessage(
            content=message.get("content"),
            tool_calls=calls,
            reasoning_content=message.get("reasoning_content"),
        )
