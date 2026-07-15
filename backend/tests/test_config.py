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
