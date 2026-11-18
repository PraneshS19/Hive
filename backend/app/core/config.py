import json
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "hedgelab.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "HIVE Backend"
    PROJECT_NAME: str = "HIVE"
    PROJECT_TAGLINE: str = "Analyze. Evaluate. Evolve."
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    CORS_ORIGINS: list[str] | str = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [i.strip() for i in v.split(",") if i.strip()]
        return v

    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    # Market Data Mode & Invariants
    MARKET_DATA_PROVIDER: str = "0xramm_yahoo_rest"  # "0xramm_yahoo_rest", "ramm_stock_api", or "dhanhq_live"
    MARKET_DATA_MODE: str = "LIVE_ONLY"
    MARKET_DATA_BASE_URL: str = "http://127.0.0.1:8787"
    MARKET_DATA_RESPONSE_MODE: str = "num"
    MARKET_DATA_POLL_INTERVAL_SECONDS: float = 15.0
    MARKET_DATA_REQUEST_TIMEOUT_SECONDS: float = 8.0
    MARKET_DATA_MAX_RETRIES: int = 2
    MARKET_DATA_BACKOFF_FACTOR: float = 1.5
    MARKET_DATA_STALE_AFTER_SECONDS: float = 60.0
    MARKET_DATA_TIMEZONE: str = "Asia/Kolkata"
    MARKET_DATA_ALLOW_HISTORICAL_FALLBACK: bool = False
    MARKET_DATA_ALLOW_SYNTHETIC_MARKET_DATA: bool = False

    ALLOW_HISTORICAL_MARKET_FALLBACK: bool = False
    ALLOW_SYNTHETIC_MARKET_DATA: bool = False
    SYNTHETIC_RANDOM_SEED: int = 42

    # 0xramm Indian Stock Market API Adapter Backward-Compatible Aliases
    RAM_STOCK_API_BASE_URL: str = "http://127.0.0.1:8787"
    RAM_POLL_INTERVAL_SECONDS: float = 15.0
    RAM_REQUEST_TIMEOUT_SECONDS: float = 8.0
    RAM_MAX_RETRIES: int = 2
    RAM_BACKOFF_FACTOR: float = 1.5
    RAM_STALENESS_THRESHOLD_SECONDS: float = 60.0
    RAM_FEED_ENABLED: bool = True
    RAM_EMBEDDED_FALLBACK: bool = True
    RAM_BATCH_WRITE_SECONDS: float = 5.0
    RAM_MARKET_OPEN_TIME: str = "09:15"
    RAM_MARKET_CLOSE_TIME: str = "15:30"

    # Local LLM (Ollama) Settings
    OLLAMA_ENABLED: bool = True
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:4b"
    OLLAMA_TIMEOUT_SECONDS: float = 45.0

    # Multi-Agent Continuous Review & Improvement Settings
    HIVE_EXECUTOR_MODEL: str = Field(
        default="qwen3.5:4b",
        validation_alias=AliasChoices("HIVE_EXECUTOR_MODEL", "HEDGELAB_EXECUTOR_MODEL"),
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$",
    )
    HIVE_REVIEWER_MODEL: str = Field(
        default="hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M",
        validation_alias=AliasChoices("HIVE_REVIEWER_MODEL", "HEDGELAB_REVIEWER_MODEL"),
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$",
    )
    HIVE_OPERATOR_TOKEN: str = Field(default="", repr=False)

    @model_validator(mode="after")
    def validate_model_roles(self):
        def model_tag(name: str) -> str:
            return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"

        if model_tag(self.HIVE_EXECUTOR_MODEL).casefold() == model_tag(self.HIVE_REVIEWER_MODEL).casefold():
            raise ValueError("Executor and reviewer must use distinct Ollama models")
        return self
    HEDGELAB_MODEL_TIMEOUT_SECONDS: float = 45.0
    HEDGELAB_MODEL_KEEP_ALIVE: str = "0"
    HEDGELAB_MAX_REVISION_ATTEMPTS: int = 1
    HEDGELAB_REVIEW_ENABLED: bool = True
    HEDGELAB_IMPROVEMENT_ENABLED: bool = True
    MIN_EVAL_SAMPLE_THRESHOLD: int = 3

    # DhanHQ Live Market-Data Ingestion Settings
    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""
    DHAN_FEED_ENABLED: bool = False
    DHAN_FEED_MODE: str = "QUOTE"  # "TICKER", "QUOTE", or "FULL"
    DHAN_STALENESS_THRESHOLD_SECONDS: float = 15.0
    DHAN_RECONNECT_MAX_ATTEMPTS: int = 5
    DHAN_RECONNECT_BASE_DELAY_SECONDS: float = 2.0
    DHAN_QUEUE_MAXSIZE: int = 1000
    DHAN_BATCH_WRITE_SECONDS: float = 5.0
    DHAN_TRADING_EXCHANGE: str = "NSE"
    DHAN_MARKET_OPEN_TIME: str = "09:15"
    DHAN_MARKET_CLOSE_TIME: str = "15:30"

    # Event Detection & Cooldown Settings
    EVENT_PRICE_CHANGE_THRESHOLD_PCT: float = 1.5
    EVENT_VOLUME_SPIKE_RATIO: float = 3.0
    EVENT_COOLDOWN_SECONDS: float = 60.0
    EVENT_MAX_PENDING: int = 50

    # Default Simulation & Risk Parameters
    INITIAL_CASH: float = 1000000.0
    INITIAL_EQUITY: float = 1000000.0
    TRANSACTION_FEE_PCT: float = 0.1
    COMMISSION_PCT: float = 0.1
    SLIPPAGE_PCT: float = 0.05
    MAX_ORDER_PCT: float = 10.0
    MAX_ALLOCATION_PCT: float = 25.0
    MAX_DRAWDOWN_PCT: float = 10.0
    AUTO_EXECUTE: bool = True


settings = Settings()
