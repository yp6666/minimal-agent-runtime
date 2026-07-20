from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PACKAGE_DIR = Path(__file__).resolve().parent
load_dotenv(PACKAGE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    tavily_api_key: str
    qweather_api_key: str
    qweather_weather_base: str
    qweather_geo_base: str
    database_path: Path
    max_agent_steps: int
    recent_message_limit: int
    compact_after_messages: int

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
            ).rstrip("/"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            qweather_api_key=os.getenv("QWEATHER_API_KEY", ""),
            # Legacy shared domains are kept only because this demo explicitly
            # requests API-key-only setup. They can be replaced through env vars.
            qweather_weather_base=os.getenv(
                "QWEATHER_WEATHER_BASE", "https://devapi.qweather.com"
            ).rstrip("/"),
            qweather_geo_base=os.getenv(
                "QWEATHER_GEO_BASE", "https://geoapi.qweather.com"
            ).rstrip("/"),
            database_path=Path(
                os.getenv("AGENT_DATABASE_PATH", PACKAGE_DIR / "agent.db")
            ),
            max_agent_steps=max(1, int(os.getenv("MAX_AGENT_STEPS", "6"))),
            recent_message_limit=max(
                4, int(os.getenv("RECENT_MESSAGE_LIMIT", "16"))
            ),
            compact_after_messages=max(
                8, int(os.getenv("COMPACT_AFTER_MESSAGES", "24"))
            ),
        )

    def missing_credentials(self) -> list[str]:
        pairs = {
            "DEEPSEEK_API_KEY": self.deepseek_api_key,
            "TAVILY_API_KEY": self.tavily_api_key,
            "QWEATHER_API_KEY": self.qweather_api_key,
        }
        return [name for name, value in pairs.items() if not value]
