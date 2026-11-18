"""Application settings (pydantic-settings). All values come from env / .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- App ----
    app_name: str = "Bohurupi API"
    env: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    web_origin: str = "http://localhost:3000"

    # ---- Persistence ----
    database_url: str = "sqlite:///./bohurupi.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_path: str = "./storage"

    # ---- Auth ----
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    admin_email: str = "admin@example.com"
    google_client_id: str = ""
    google_client_secret: str = ""

    # ---- LLM (Z.AI GLM, OpenAI-compatible) ----
    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/paas/v4/"
    zai_model: str = "glm-4.6"

    # ---- Agent tools ----
    tavily_api_key: str = ""

    # ---- TTS engines ----
    engine_order: str = "kokoro,edge"
    kokoro_auto_download: bool = True
    whisper_model_size: str = "base"

    # ---- Safety ----
    watermark_enabled: bool = True
    max_upload_mb: int = 20

    # ---- Plan quotas (TTS chars / day) ----
    quota_free_chars: int = 20_000
    quota_pro_chars: int = 200_000
    quota_studio_chars: int = 1_000_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def engine_order_list(self) -> list[str]:
        return [e.strip().lower() for e in self.engine_order.split(",") if e.strip()]

    @property
    def quota_by_plan(self) -> dict[str, int]:
        return {
            "free": self.quota_free_chars,
            "pro": self.quota_pro_chars,
            "studio": self.quota_studio_chars,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
