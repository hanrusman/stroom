import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://stroom:password@localhost:5433/stroom"
    ASYNC_DATABASE_URL: str = (
        "postgresql+asyncpg://stroom:password@localhost:5433/stroom"
    )
    SQL_ECHO: bool = False

    # LiteLLM
    LITELLM_URL: str = "http://stroom-litellm:4000/v1/chat/completions"
    LITELLM_MASTER_KEY: str = "sk-default"

    # API Keys
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
