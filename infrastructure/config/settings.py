from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Central configuration for all engines and services.
    
    Configuration hierarchy:
    .env file → Settings() → Dependency Injection → Engine
    
    No component reads environment variables directly.
    """

    # Application
    app_name: str = Field(default="polis", env="APP_NAME")
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")

    # API
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")

    # Database
    database_url: str = Field(default="sqlite:///polis.db", env="DATABASE_URL")
    database_echo: bool = Field(default=False, env="DATABASE_ECHO")

    # Vector Storage
    vector_store_url: str = Field(default="localhost:6333", env="VECTOR_STORE_URL")

    # Authentication
    jwt_secret: str = Field(default="dev-secret", env="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expiration_hours: int = Field(default=24, env="JWT_EXPIRATION_HOURS")

    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(default="json", env="LOG_FORMAT")

    # Feature Flags
    enable_reasoning_engine: bool = Field(
        default=True, env="ENABLE_REASONING_ENGINE"
    )
    enable_governance_engine: bool = Field(
        default=True, env="ENABLE_GOVERNANCE_ENGINE"
    )

    class Config:
        """Pydantic configuration."""

        env_file: str = ".env"
        env_file_encoding: str = "utf-8"
        case_sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary."""
        return self.model_dump()

    def to_json(self) -> str:
        """Convert settings to JSON string."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_env_file(cls, env_file: str | Path = ".env") -> Settings:
        """Load settings from environment file."""
        if isinstance(env_file, str):
            env_file = Path(env_file)

        if env_file.exists():
            return cls(_env_file=env_file)
        return cls()

    def validate_critical_settings(self) -> None:
        """Validate critical configuration settings.
        
        Raises:
            ValueError: If critical settings are invalid or missing.
        """
        if self.environment == "production":
            if self.jwt_secret == "dev-secret":
                msg = "JWT_SECRET must be set in production"
                raise ValueError(msg)
            if self.debug:
                msg = "DEBUG must be False in production"
                raise ValueError(msg)
