from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "meeting-bot-handler"
    environment: str = "development"

    host: str = "0.0.0.0"
    port: int = 8000

    redis_url: str = "redis://localhost:6379/0"

    kubernetes_namespace: str = "meeting-bots"

    bot_image: str = "meeting-bot:latest"

    meeting_api_url: str = "http://meeting-api:8000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
