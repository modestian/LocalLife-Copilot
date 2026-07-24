import re
from functools import lru_cache
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LocalLife Copilot API"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    log_level: str = "INFO"
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
    opensearch_index: str = "local-life-chunks"
    opensearch_index_version: int = 1
    embedding_dimension: int = 512
    embedding_batch_size: int = 32
    embedding_model: str = "local-deterministic-v1"
    embedding_model_name: str = "BAAI/bge-small-zh-v1.5"
    generation_model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"
    knowledge_data_root: str = "/data/knowledge"
    training_artifact_root: str = "/data/training/artifacts"
    max_ingestion_source_bytes: int = 20 * 1024 * 1024
    model_gateway_health_url: str = "http://model-gateway:8001/health/live"
    model_gateway_embedding_url: str = "http://model-gateway:8001/v1/embeddings"
    model_gateway_generate_url: str = "http://model-gateway:8001/v1/generate"
    model_gateway_sentiment_url: str = "http://model-gateway:8001/v1/sentiment/batch"
    dependency_timeout_seconds: float = 2.0
    bailian_api_key: str = ""
    bailian_model: str = "qwen-plus"
    bailian_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    search_minimum_score: float = 0.2
    jwt_secret_key: SecretStr = SecretStr("development-only-change-this-jwt-secret-key")
    jwt_issuer: str = "local-life-copilot"
    jwt_audience: str = "local-life-copilot-api"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
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

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be a standard Python logging level")
        return normalized

    @field_validator("access_token_ttl_minutes")
    @classmethod
    def validate_access_token_ttl(cls, value: int) -> int:
        if not 1 <= value <= 1440:
            raise ValueError("access_token_ttl_minutes must be between 1 and 1440")
        return value

    @field_validator("refresh_token_ttl_days")
    @classmethod
    def validate_refresh_token_ttl(cls, value: int) -> int:
        if not 1 <= value <= 90:
            raise ValueError("refresh_token_ttl_days must be between 1 and 90")
        return value

    @field_validator("login_rate_limit_attempts")
    @classmethod
    def validate_login_rate_limit_attempts(cls, value: int) -> int:
        if not 2 <= value <= 100:
            raise ValueError("login_rate_limit_attempts must be between 2 and 100")
        return value

    @field_validator("login_rate_limit_window_seconds")
    @classmethod
    def validate_login_rate_limit_window(cls, value: int) -> int:
        if not 10 <= value <= 3600:
            raise ValueError("login_rate_limit_window_seconds must be between 10 and 3600")
        return value

    @field_validator("max_ingestion_source_bytes")
    @classmethod
    def validate_max_ingestion_source_bytes(cls, value: int) -> int:
        if not 1 <= value <= 1024 * 1024 * 1024:
            raise ValueError("max_ingestion_source_bytes must be between 1 byte and 1 GiB")
        return value

    @field_validator("opensearch_index")
    @classmethod
    def validate_opensearch_index(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", normalized):
            raise ValueError("opensearch_index must be a valid lowercase index prefix")
        return normalized

    @field_validator("opensearch_index_version", "embedding_dimension", "embedding_batch_size")
    @classmethod
    def validate_positive_search_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OpenSearch index version and embedding settings must be positive")
        return value

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("embedding_model must not be blank")
        return normalized

    @field_validator("search_minimum_score")
    @classmethod
    def validate_search_minimum_score(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("search_minimum_score must be between 0 and 1")
        return value

    @field_validator("jwt_issuer", "jwt_audience")
    @classmethod
    def validate_jwt_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("JWT issuer and audience must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        secret = self.jwt_secret_key.get_secret_value()
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("jwt_secret_key must contain at least 32 bytes")
        if self.app_environment.lower() in {"production", "prod"} and secret.startswith(
            "development-only-"
        ):
            raise ValueError("production must override the development JWT secret")
        return self

    @property
    def database_url(self) -> str:
        return (
            f"mysql+asyncmy://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{quote_plus(self.mysql_database)}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{quote_plus(self.mysql_database)}?charset=utf8mb4"
        )

    @property
    def opensearch_concrete_index(self) -> str:
        return f"{self.opensearch_index}-v{self.opensearch_index_version}"

    @property
    def opensearch_read_alias(self) -> str:
        return f"{self.opensearch_index}-read"

    @property
    def opensearch_write_alias(self) -> str:
        return f"{self.opensearch_index}-write"


@lru_cache
def get_settings() -> Settings:
    return Settings()
