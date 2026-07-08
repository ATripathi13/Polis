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


class Settings(BaseSettings):
    """
    Central application configuration.

    This is the ONLY class allowed to read values from the .env file.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
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

    postgres_host: str = Field(alias="POSTGRES_HOST")
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

    # ==========================================================
    # Security
    # ==========================================================

    jwt_secret: str = Field(alias="JWT_SECRET")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.
    """
    return Settings()