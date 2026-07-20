from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field

from minimal_agent.models import ToolResult

from .base import AgentTool


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500, description="搜索问题或关键词")
    max_results: int = Field(default=3, ge=1, le=5, description="返回结果数量")
    topic: str = Field(default="general", pattern="^(general|news)$")


class TavilySearchTool(AgentTool):
    name = "search"
    description = "搜索互联网中的最新信息，并返回带来源 URL 的结果。"
    args_model = SearchArgs

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.client = client

    async def execute(self, arguments: SearchArgs, *, session_id: str) -> ToolResult:
        del session_id
        if not self.api_key:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="MISSING_API_KEY",
                message="缺少 TAVILY_API_KEY",
            )

        payload = {
            "query": arguments.query,
            "max_results": arguments.max_results,
            "topic": arguments.topic,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        try:
            if self.client is not None:
                response = await self._request(self.client, payload)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await self._request(client, payload)
            data = response.json()
            results = [
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "content": (item.get("content") or "")[:1200],
                    "score": item.get("score"),
                }
                for item in data.get("results", [])[: arguments.max_results]
            ]
            return ToolResult(
                ok=True,
                tool_name=self.name,
                data={
                    "query": arguments.query,
                    "results": results,
                    "request_id": data.get("request_id"),
                },
            )
        except httpx.TimeoutException:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="SEARCH_TIMEOUT",
                message="Tavily 请求超时",
            )
        except httpx.HTTPStatusError as error:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="SEARCH_HTTP_ERROR",
                message=f"Tavily 返回 HTTP {error.response.status_code}",
            )
        except httpx.RequestError as error:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="SEARCH_NETWORK_ERROR",
                message=f"无法连接 Tavily：{type(error).__name__}",
            )
        except ValueError:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="INVALID_SEARCH_RESPONSE",
                message="Tavily 返回了无法解析的数据",
            )

    async def _request(
        self, client: httpx.AsyncClient, payload: dict
    ) -> httpx.Response:
        response = await client.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response
