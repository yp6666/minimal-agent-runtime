from __future__ import annotations

from datetime import date as date_type

import httpx
from pydantic import BaseModel, ConfigDict, Field

from minimal_agent.models import ToolResult

from .base import AgentTool


class WeatherArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1, max_length=100, description="城市或地区名称")
    date: str | None = Field(
        default=None,
        description="YYYY-MM-DD；不传表示实时天气，未来日期表示天气预报",
    )


class QWeatherTool(AgentTool):
    name = "weather"
    description = "查询城市的实时天气或未来天气预报。日期必须使用 YYYY-MM-DD。"
    args_model = WeatherArgs

    def __init__(
        self,
        api_key: str,
        weather_base: str,
        geo_base: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.weather_base = weather_base.rstrip("/")
        self.geo_base = geo_base.rstrip("/")
        self.client = client
        self._location_cache: dict[str, dict] = {}

    async def execute(self, arguments: WeatherArgs, *, session_id: str) -> ToolResult:
        del session_id
        if not self.api_key:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="MISSING_API_KEY",
                message="缺少 QWEATHER_API_KEY",
            )
        if arguments.date:
            try:
                date_type.fromisoformat(arguments.date)
            except ValueError:
                return ToolResult(
                    ok=False,
                    tool_name=self.name,
                    error_code="INVALID_DATE",
                    message="date 必须使用 YYYY-MM-DD 格式",
                )

        try:
            if self.client is not None:
                return await self._execute_with_client(self.client, arguments)
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await self._execute_with_client(client, arguments)
        except httpx.TimeoutException:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="WEATHER_TIMEOUT",
                message="和风天气请求超时",
            )
        except httpx.HTTPStatusError as error:
            error_code = "WEATHER_HTTP_ERROR"
            message = f"和风天气返回 HTTP {error.response.status_code}"
            try:
                payload = error.response.json().get("error", {})
                error_type = str(payload.get("type", ""))
                detail = str(payload.get("detail", ""))
                if "invalid-host" in error_type:
                    error_code = "INVALID_HOST"
                    message = "和风天气拒绝了公共域名，需要使用账户专属 API Host"
                elif detail:
                    message = detail[:300]
            except (TypeError, ValueError):
                pass
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code=error_code,
                message=message,
            )
        except httpx.RequestError as error:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="WEATHER_NETWORK_ERROR",
                message=f"无法连接和风天气：{type(error).__name__}",
            )
        except ValueError:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="INVALID_WEATHER_RESPONSE",
                message="和风天气返回了无法解析的数据",
            )

    async def _execute_with_client(
        self, client: httpx.AsyncClient, arguments: WeatherArgs
    ) -> ToolResult:
        location = await self._lookup_location(client, arguments.city)
        if location is None:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="CITY_NOT_FOUND",
                message=f"没有找到城市：{arguments.city}",
            )
        if arguments.date is None:
            return await self._current(client, location)
        return await self._forecast(client, location, arguments.date)

    @property
    def headers(self) -> dict[str, str]:
        return {"X-QW-Api-Key": self.api_key, "Accept-Encoding": "gzip"}

    async def _lookup_location(
        self, client: httpx.AsyncClient, city: str
    ) -> dict | None:
        cache_key = city.strip().lower()
        if cache_key in self._location_cache:
            return self._location_cache[cache_key]
        # The retired shared GeoAPI host used /v2, while dedicated API Hosts
        # use /geo/v2. Supporting both keeps the tool configuration-driven.
        geo_path = (
            "/v2/city/lookup"
            if "geoapi.qweather.com" in self.geo_base
            else "/geo/v2/city/lookup"
        )
        response = await client.get(
            f"{self.geo_base}{geo_path}",
            headers=self.headers,
            params={"location": city, "number": 1, "lang": "zh"},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "200":
            raise ValueError(f"QWeather code={data.get('code')}")
        locations = data.get("location") or []
        if not locations:
            return None
        self._location_cache[cache_key] = locations[0]
        return locations[0]

    async def _current(
        self, client: httpx.AsyncClient, location: dict
    ) -> ToolResult:
        response = await client.get(
            f"{self.weather_base}/v7/weather/now",
            headers=self.headers,
            params={"location": location["id"], "lang": "zh", "unit": "m"},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "200":
            raise ValueError(f"QWeather code={data.get('code')}")
        now = data["now"]
        return ToolResult(
            ok=True,
            tool_name=self.name,
            data={
                "mode": "current",
                "location": self._location_view(location),
                "weather": {
                    "observed_at": now.get("obsTime"),
                    "condition": now.get("text"),
                    "temperature_c": now.get("temp"),
                    "feels_like_c": now.get("feelsLike"),
                    "humidity_percent": now.get("humidity"),
                    "wind_direction": now.get("windDir"),
                    "wind_scale": now.get("windScale"),
                    "precipitation_mm": now.get("precip"),
                    "visibility_km": now.get("vis"),
                },
                "source_url": data.get("fxLink"),
            },
        )

    async def _forecast(
        self, client: httpx.AsyncClient, location: dict, target_date: str
    ) -> ToolResult:
        response = await client.get(
            f"{self.weather_base}/v7/weather/3d",
            headers=self.headers,
            params={"location": location["id"], "lang": "zh", "unit": "m"},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "200":
            raise ValueError(f"QWeather code={data.get('code')}")
        forecast = next(
            (item for item in data.get("daily", []) if item.get("fxDate") == target_date),
            None,
        )
        if forecast is None:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="DATE_OUT_OF_RANGE",
                message="当前最小版本仅支持实时和未来三天天气",
            )
        return ToolResult(
            ok=True,
            tool_name=self.name,
            data={
                "mode": "forecast",
                "location": self._location_view(location),
                "weather": {
                    "date": forecast.get("fxDate"),
                    "day_condition": forecast.get("textDay"),
                    "night_condition": forecast.get("textNight"),
                    "min_temperature_c": forecast.get("tempMin"),
                    "max_temperature_c": forecast.get("tempMax"),
                    "humidity_percent": forecast.get("humidity"),
                    "precipitation_mm": forecast.get("precip"),
                    "wind_direction": forecast.get("windDirDay"),
                    "wind_scale": forecast.get("windScaleDay"),
                },
                "source_url": data.get("fxLink"),
            },
        )

    @staticmethod
    def _location_view(location: dict) -> dict:
        return {
            "name": location.get("name"),
            "adm1": location.get("adm1"),
            "adm2": location.get("adm2"),
            "timezone": location.get("tz"),
            "location_id": location.get("id"),
        }
