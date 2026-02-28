from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    ENV: str = "development"  # development | production
    LOG_LEVEL: str = "info"

    # Mongo
    MONGO_URI: str = ""
    MONGO_DB: str = "famconn"

    # Security
    JWT_SECRET: str = "CHANGE_ME"
    JWT_ISSUER: str = "famconn-api"
    JWT_AUDIENCE: str = "famconn-mobile"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30

    # Rate limiting
    LOGIN_RATE_LIMIT_MAX: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    # CORS (comma-separated)
    CORS_ORIGINS: str = ""


settings = Settings()
