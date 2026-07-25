import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_build_database_url() -> None:
    settings = Settings(
        mysql_user="app",
        mysql_password="dev@password",
        mysql_host="database",
        mysql_port=3307,
        mysql_database="catalog",
    )

    assert settings.database_url == (
        "mysql+asyncmy://app:dev%40password@database:3307/catalog?charset=utf8mb4"
    )


def test_settings_accept_comma_separated_cors_origins() -> None:
    settings = Settings(cors_origins="http://localhost:3000, http://127.0.0.1:3000")

    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_settings_normalize_api_prefix() -> None:
    settings = Settings(api_v1_prefix=" /custom/v1/ ")

    assert settings.api_v1_prefix == "/custom/v1"


@pytest.mark.parametrize("value", [0, 1024 * 1024 * 1024 + 1])
def test_settings_reject_invalid_ingestion_size_limit(value: int) -> None:
    with pytest.raises(ValidationError, match="max_ingestion_source_bytes"):
        Settings(max_ingestion_source_bytes=value)


@pytest.mark.parametrize("value", ["relative", "/", ""])
def test_settings_reject_invalid_api_prefix(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(api_v1_prefix=value)


@pytest.mark.parametrize("value", ["", "X Request ID", "X-Request-ID:"])
def test_settings_reject_invalid_request_id_header(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(request_id_header=value)


def test_settings_reject_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(jwt_secret_key="too-short")


def test_production_rejects_development_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="production must override"):
        Settings(app_environment="production")

    settings = Settings(app_environment="production", jwt_secret_key="p" * 32)
    assert settings.jwt_secret_key.get_secret_value() == "p" * 32


@pytest.mark.parametrize("value", [0, -1])
def test_settings_reject_invalid_embedding_batch_size(value: int) -> None:
    with pytest.raises(ValidationError, match="embedding settings"):
        Settings(embedding_batch_size=value)


def test_settings_reject_blank_embedding_model() -> None:
    with pytest.raises(ValidationError, match="embedding_model"):
        Settings(embedding_model=" ")


@pytest.mark.parametrize("value", [0, 301])
def test_settings_reject_invalid_embedding_request_timeout(value: float) -> None:
    with pytest.raises(ValidationError, match="embedding_request_timeout_seconds"):
        Settings(embedding_request_timeout_seconds=value)


@pytest.mark.parametrize("value", [0, 11])
def test_settings_reject_invalid_embedding_request_attempts(value: int) -> None:
    with pytest.raises(ValidationError, match="embedding_request_max_attempts"):
        Settings(embedding_request_max_attempts=value)


@pytest.mark.parametrize("value", [1, 101])
def test_settings_reject_invalid_login_rate_limit_attempts(value: int) -> None:
    with pytest.raises(ValidationError, match="login_rate_limit_attempts"):
        Settings(login_rate_limit_attempts=value)


@pytest.mark.parametrize("value", [9, 3601])
def test_settings_reject_invalid_login_rate_limit_window(value: int) -> None:
    with pytest.raises(ValidationError, match="login_rate_limit_window_seconds"):
        Settings(login_rate_limit_window_seconds=value)
