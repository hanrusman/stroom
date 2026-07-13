"""Centrale configuratie (verbeterplan R2).

Eén plek voor alle env-knoppen. pydantic-settings valideert types bij boot
(fail-fast bij typo's) en `.env.example` kan hieruit worden afgeleid.
Modules importeren `settings` en lezen er attributen van; de oude losse
`os.environ.get`-constanten zijn aliases geworden op hun oorspronkelijke plek.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database (geen defaults: fail-fast als .env ontbreekt) ---
    DATABASE_URL: str
    ASYNC_DATABASE_URL: str
    SQL_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # --- LiteLLM / LLM-calls ---
    LITELLM_URL: str = "http://stroom-litellm:4000/v1/chat/completions"
    LITELLM_MASTER_KEY: str
    LLM_HTTP_TIMEOUT_SEC: float = 60.0
    LLM_MAX_CONCURRENT: int = 4

    # --- Externe integraties ---
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OBSIDIAN_BASE_URL: str = "http://host.docker.internal:27124"
    OBSIDIAN_API_KEY: str = ""
    VIKUNJA_URL: str = ""
    VIKUNJA_TOKEN: str = ""
    VIKUNJA_DEFAULT_PROJECT_ID: int = 1
    TRANSCRIBE_AGENT_URL: str = "http://transcribe-agent:8080"

    # --- Queue & workers ---
    SUMMARIZE_QUEUE_MAX_DEPTH: int = 30
    TRANSCRIBE_QUEUE_MAX_DEPTH: int = 30
    SUMMARIZE_WORKERS: int = 2
    SUMMARIZE_MAX_ATTEMPTS: int = 3
    SUMMARIZE_RETRY_BASE_SEC: float = 2.0
    WORKER_IDLE_POLL_SEC: float = 10.0
    TRANSCRIBE_TRIGGER_MAX_TRIES: int = 3

    # --- Mem-gate (host-RAM-drempels vóór claimen) ---
    TRANSCRIBE_MIN_FREE_MB: int = 50
    SUMMARIZE_MIN_FREE_MB: int = 150

    # --- Lange-transcript-routering ---
    LONG_TRANSCRIPT_DURATION_SECONDS: int = 600
    LONG_TRANSCRIPT_CHAR_FALLBACK: int = 20000
    LONG_TRANSCRIPT_MAX_CHARS: int = 150000
    LONG_TRANSCRIPT_MODEL: str = "cloud-kimi"
    LONG_TRANSCRIPT_TIMEOUT_SEC: float = 600.0
    ARTICLE_MIN_BODY_FOR_LESSONS: int = 800

    # --- Quality / interest scoring ---
    QUALITY_HYBRID_QUALITY_WEIGHT: float = 0.4
    QUALITY_HYBRID_INTEREST_WEIGHT: float = 0.6
    QUALITY_BOOST_FACTOR: float = 2.0
    QUALITY_SCORER_DEBUG: bool = False
    QUALITY_EMBEDDING_ENABLED: bool = True
    EMBEDDING_SIM_LOW: float = 0.866
    EMBEDDING_SIM_HIGH: float = 0.908
    INTEREST_TANH_MU: float = -0.029
    INTEREST_TANH_SIGMA: float = 0.009
    EMBED_SERVICE_URL: str = ""
    EMBED_TIMEOUT_SEC: float = 5.0
    EMBED_BREAKER_THRESHOLD: int = 5
    EMBED_BREAKER_COOLDOWN_SEC: float = 60.0
    EMBED_MAX_CONCURRENCY: int = 4

    # --- Web/security ---
    STROOM_ENABLE_DOCS: bool = False
    STROOM_ALLOWED_ORIGINS: str = ""
    STROOM_INTERNAL_TOKEN: str = ""
    STROOM_INBOX_TOKEN: str = ""
    STROOM_INSECURE_COOKIE: bool = False
    STROOM_TRUSTED_PROXIES: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        defaults = ["http://localhost:3000", "http://localhost:8101"]
        extra = [o.strip() for o in self.STROOM_ALLOWED_ORIGINS.split(",") if o.strip()]
        return list(dict.fromkeys(defaults + extra))

    @property
    def trusted_proxies(self) -> set[str]:
        return {ip.strip() for ip in self.STROOM_TRUSTED_PROXIES.split(",") if ip.strip()}


settings = Settings()
