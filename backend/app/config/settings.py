"""Runtime configuration for the H.O.L.M.E.V backend.

Every value has a safe, local-first default. Nothing here may assume a network
provider exists.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App / security ---
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    JWT_SECRET: str = "change_me_in_production"
    SECRET_KEY: str = "change_me_in_production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    API_TOKEN: str = ""
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,tauri://localhost"

    # --- Persistence ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./holmev.db"
    WORKSPACE_ROOT: str = "./workspace"
    UNDO_RETENTION_DAYS: int = 7

    # --- Local models (Ollama) ---
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_DEFAULT_MODEL: str = "qwen2.5:3b"
    OLLAMA_CHAT_MODEL: str = "qwen2.5:3b"
    OLLAMA_CODER_MODEL: str = "qwen2.5-coder:7b"
    OLLAMA_REASONING_MODEL: str = "qwen2.5:7b"
    OLLAMA_TIMEOUT_S: float = 120.0
    OLLAMA_KEEP_ALIVE: str = "5m"
    OLLAMA_NUM_CTX: int = 8192

    # --- External models (disabled unless a key is present) ---
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_PROVIDER_LABEL: str = "openai"
    OPENAI_DEFAULT_MODEL: str = "gpt-4o-mini"
    GEMINI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    # Fill with the provider's published price; 0.0 means "not configured",
    # never "free". The UI labels any estimate as an estimate.
    EXTERNAL_COST_PER_1K_INPUT_USD: float = 0.0
    EXTERNAL_COST_PER_1K_OUTPUT_USD: float = 0.0

    # Which provider the brain prefers first: "ollama" | "external" | "mock"
    BRAIN_PRIMARY_PROVIDER: str = "ollama"
    BRAIN_ALLOW_EXTERNAL: bool = False

    # --- Privacy ---
    # local_only | allow_external_with_consent | allow_external
    PRIVACY_LEVEL: str = "local_only"

    # --- Routing weights (deterministic, explained in the UI) ---
    W_CAPABILITY: float = 3.0
    W_CONTEXT: float = 1.5
    W_SPEED: float = 1.0
    W_PREFERENCE: float = 1.0
    W_COST: float = 1.0
    W_PRIVACY: float = 2.0

    # --- Orchestration limits ---
    MAX_STEPS_PER_RUN: int = 12
    MAX_PLAN_JSON_REPAIRS: int = 2
    STAGE_TIMEOUT_S: float = 120.0
    APPROVAL_EXPIRY_S: int = 300
    APPROVAL_MIN_LEVEL: int = 2
    RATE_LIMIT_PER_MIN: int = 60

    # --- Memory ---
    MEMORY_TOKEN_BUDGET: int = 900
    MEMORY_MAX_ROWS: int = 2000
    CONVERSATION_HISTORY_TURNS: int = 8
    CONTEXT_TOKEN_BUDGET: int = 6000

    # --- Voice / vision / home ---
    STT_PROVIDER: str = "local"
    TTS_PROVIDER: str = "local"
    CUSTOM_VOICE_PROVIDER: str = "local"
    CUSTOM_VOICE_ID: str = "holmev_voice_prime"
    WAKE_WORD_ENABLED: bool = False

    # --- Host control ---
    # Off by default: shutting the machine down is not something a model may do
    # because a plan said so. Set true only when this box is expendable.
    ALLOW_SYSTEM_POWER_ACTIONS: bool = False

    HOME_DEVICE_MODE: str = "SIMULATED"
    # JSON object mapping a room tag to that camera's stream URL, e.g.
    # CAMERAS={"bedroom":"http://192.168.1.40:8080/video","hall":"rtsp://..."}
    # Rooms may be declared without a URL; those entries admit they have no feed.
    CAMERAS: str = ""
    CAMERA_PROBE_TIMEOUT_S: float = 3.0
    MQTT_BROKER_URL: str = "mqtt://localhost:1883"
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    ESP32_GATEWAY_URL: str = "http://192.168.1.100"
    # The HTTP endpoint of a real IR emitter board. Empty means no emitter exists,
    # and the IR engine then refuses to claim a pulse was sent.
    IR_GATEWAY_URL: str = ""

    DESKTOP_AGENT_URL: str = "http://localhost:8000"
    DESKTOP_AGENT_TOKEN: str = ""

    # --- Communication ---
    # WhatsApp, dialling and the phone gallery need something on the far side.
    # Blank means nothing is paired, and the bridge refuses instead of claiming a send.
    MOBILE_BRIDGE_URL: str = ""
    MOBILE_BRIDGE_TOKEN: str = ""
    # Email really does send once these are filled (any SMTP provider works, including
    # a Gmail app password or a local server). The password stays in .env.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_ADDRESS: str = ""
    SMTP_USE_TLS: bool = True

    VISION_CAMERA_INDEX: int = 0
    GESTURE_ENABLED: bool = False

    # --- Navigation ---
    # Blank means there is no map, and the route engine says so instead of inventing
    # a distance. A local OSRM/Valhalla container is the private option; the public
    # demo server works too but sends your coordinates to someone else's machine.
    OSRM_BASE_URL: str = ""
    NOMINATIM_BASE_URL: str = ""
    # Only used to answer "from my home" when no origin is given. 0.0 means unset.
    HOME_LATITUDE: float = 0.0
    HOME_LONGITUDE: float = 0.0

    # --- Limits ---
    MAX_UPLOAD_SIZE_MB: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def external_enabled(self) -> bool:
        return bool(self.OPENAI_API_KEY) and self.BRAIN_ALLOW_EXTERNAL and self.PRIVACY_LEVEL != "local_only"


settings = Settings()
