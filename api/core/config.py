import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database - Defaults removed to fail-fast if .env is missing
    DATABASE_URL: str
    ASYNC_DATABASE_URL: str
    SQL_ECHO: bool = False

    # LiteLLM
    LITELLM_URL: str = "http://stroom-litellm:4000/v1/chat/completions"
    LITELLM_MASTER_KEY: str

    # API Keys
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"

    # Obsidian Local REST API
    OBSIDIAN_BASE_URL: str = "http://host.docker.internal:27124"
    OBSIDIAN_API_KEY: str = ""

    # Vikunja API
    VIKUNJA_URL: str = ""
    VIKUNJA_TOKEN: str = ""
    VIKUNJA_DEFAULT_PROJECT_ID: int = 1

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
