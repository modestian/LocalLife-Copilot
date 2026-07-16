import re
from functools import lru_cache
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LocalLife Copilot API"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    request_id_header: str = "X-Request-ID"
    request_id_max_length: int = 128
    mysql_database: str = "local_life"
    mysql_user: str = "local_life"
    mysql_password: str = "local_life_dev"
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    redis_url: str = "redis://redis:6379/0"
    opensearch_url: str = "http://opensearch:9200"
    opensearch_index: str = "local-life-documents"
    model_gateway_health_url: str = "http://model-gateway:8001/health/live"
    dependency_timeout_seconds: float = 2.0
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/") or normalized == "/":
            raise ValueError("api_v1_prefix must be an absolute non-root path")
        return normalized.rstrip("/")

    @field_validator("request_id_max_length")
    @classmethod
    def validate_request_id_max_length(cls, value: int) -> int:
        if not 16 <= value <= 1024:
            raise ValueError("request_id_max_length must be between 16 and 1024")
        return value

    @field_validator("request_id_header")
    @classmethod
    def validate_request_id_header(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", normalized):
            raise ValueError("request_id_header must be a valid HTTP header name")
        return normalized

    @property
    def database_url(self) -> str:
        return (
            f"mysql+asyncmy://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{quote_plus(self.mysql_database)}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
