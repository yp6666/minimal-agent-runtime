from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import PACKAGE_DIR, Settings
from .context import ContextManager
from .llm import DeepSeekClient
from .models import AgentRunResult, ChatRequest, CreateSessionRequest
from .runtime import AgentRuntime
from .storage import SQLiteStore
from .tools import (
    CalculatorTool,
    QWeatherTool,
    TavilySearchTool,
    TodoTool,
    ToolRegistry,
)


def build_runtime(settings: Settings, store: SQLiteStore) -> AgentRuntime:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(TavilySearchTool(settings.tavily_api_key))
    registry.register(
        QWeatherTool(
            settings.qweather_api_key,
            settings.qweather_weather_base,
            settings.qweather_geo_base,
        )
    )
    registry.register(TodoTool(store))
    context = ContextManager(
        store,
        recent_message_limit=settings.recent_message_limit,
        compact_after_messages=settings.compact_after_messages,
    )
    llm = DeepSeekClient(
        settings.deepseek_api_key,
        settings.deepseek_base_url,
        settings.deepseek_model,
    )
    return AgentRuntime(
        llm,
        registry,
        store,
        context,
        max_steps=settings.max_agent_steps,
    )


def create_app(
    settings: Settings | None = None,
    *,
    store: SQLiteStore | None = None,
    runtime: AgentRuntime | None = None,
) -> FastAPI:
    settings = settings or Settings.load()
    store = store or SQLiteStore(settings.database_path)
    runtime = runtime or build_runtime(settings, store)

    app = FastAPI(title="MiniAgent Runtime", version="0.1.0")
    app.state.settings = settings
    app.state.store = store
    app.state.runtime = runtime

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model": settings.deepseek_model,
            "tools": runtime.registry.names(),
            "missing_credentials": settings.missing_credentials(),
            "weather_endpoint_mode": (
                "legacy-shared"
                if "qweather.com" in settings.qweather_weather_base
                and "qweatherapi.com" not in settings.qweather_weather_base
                else "dedicated-host"
            ),
        }

    @app.get("/api/sessions")
    async def list_sessions(
        user_id: str = Query(default="demo-user", min_length=1, max_length=100)
    ) -> list[dict[str, Any]]:
        return store.list_sessions(user_id)

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
        return store.create_session(request.user_id, request.title)

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        if not store.delete_session(session_id):
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
        return Response(status_code=204)

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        try:
            session = store.get_session(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "session": session,
            "messages": store.list_messages(session_id),
            "todos": store.list_todos(session_id),
            "traces": store.list_traces(session_id),
        }

    @app.post("/api/sessions/{session_id}/chat")
    async def chat(session_id: str, request: ChatRequest) -> dict[str, Any]:
        try:
            result: AgentRunResult = await runtime.run(
                session_id, request.message
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "run": result.model_dump(),
            "messages": store.list_messages(session_id),
            "todos": store.list_todos(session_id),
            "traces": store.list_traces(session_id, run_id=result.run_id),
        }

    @app.get("/api/sessions/{session_id}/traces")
    async def traces(
        session_id: str,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            store.get_session(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return store.list_traces(session_id, run_id=run_id)

    static_dir = PACKAGE_DIR / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
