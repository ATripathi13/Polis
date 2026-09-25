from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from infrastructure.config.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_ENVIRONMENT,
    DEFAULT_LOG_LEVEL,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


env_file = PROJECT_ROOT / ".env"

class Settings(BaseSettings):
    """
    Central application configuration.

    This is the ONLY class allowed to read values from the .env file.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================
    # Application
    # ==========================================================

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    environment: str = Field(default=DEFAULT_ENVIRONMENT, alias="ENVIRONMENT")
    log_level: str = DEFAULT_LOG_LEVEL

    # ==========================================================
    # PostgreSQL
    # ==========================================================

    postgres_host: str = Field(validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(alias="POSTGRES_PORT")
    postgres_db: str = Field(alias="POSTGRES_DB")
    postgres_user: str = Field(alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")

    database_url: str = Field(alias="DATABASE_URL")

    # ==========================================================
    # Qdrant
    # ==========================================================

    qdrant_host: str = Field(alias="QDRANT_HOST")
    qdrant_port: int = Field(alias="QDRANT_PORT")
    qdrant_api_key: str = Field(alias="QDRANT_API_KEY")
    qdrant_url: str = Field(alias="QDRANT_URL")

    # ==========================================================
    # MinIO
    # ==========================================================

    minio_host: str = Field(alias="MINIO_HOST")
    minio_port: int = Field(alias="MINIO_PORT")
    minio_console_port: int = Field(alias="MINIO_CONSOLE_PORT")
    minio_endpoint: str = Field(alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(
        default="polis-knowledge-base",
        alias="MINIO_BUCKET",
    )

    # ==========================================================
    # Security
    # ==========================================================

    slack_client_id: str = Field(alias="SLACK_CLIENT_ID")

    slack_client_secret: str = Field(alias="SLACK_CLIENT_SECRET")

    slack_signing_secret: str = Field(alias="SLACK_SIGNING_SECRET")

    slack_bot_token: str = Field(alias="SLACK_BOT_TOKEN")

    slack_app_token: str = Field(alias="SLACK_APP_TOKEN")

    slack_bot_user_id: str = Field(alias="SLACK_BOT_USER_ID")

    # ==========================================================
    # Microsoft Teams / Microsoft Graph
    # ==========================================================

    microsoft_graph_tenant_id: str = Field(
        alias="MICROSOFT_GRAPH_TENANT_ID"
    )

    microsoft_graph_client_id: str = Field(
        alias="MICROSOFT_GRAPH_CLIENT_ID"
    )

    microsoft_graph_client_secret: str = Field(
        alias="MICROSOFT_GRAPH_CLIENT_SECRET"
    )

    teams_webhook_url: str = Field(
        alias="TEAMS_WEBHOOK_URL"
    )
    # ==========================================================
    # LLM / OpenRouter
    # ==========================================================

    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")

    openrouter_model: str = Field(
        default="openrouter/free",
        alias="OPENROUTER_MODEL",
    )

    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    knowledge_base_embedding_model: str = Field(
        default="openai/text-embedding-3-small",
        alias="KNOWLEDGE_BASE_EMBEDDING_MODEL",
    )

@lru_cache(maxsize=1)
def get_settings() -> Settings:


    settings = Settings()


    return settings