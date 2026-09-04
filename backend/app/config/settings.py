import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    JWT_SECRET: str = "holmev_production_super_secret_jwt_key_change_me_in_prod"
    SECRET_KEY: str = "holmev_system_secret_key_3115"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    DATABASE_URL: str = "sqlite+aiosqlite:///./holmev.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    DEFAULT_AI_PROVIDER: str = "gemini"
    AI_FALLBACK_PROVIDER: str = "openai"
    
    STT_PROVIDER: str = "local"
    TTS_PROVIDER: str = "local"
    CUSTOM_VOICE_PROVIDER: str = "local"
    CUSTOM_VOICE_ID: str = "holmev_voice_prime"
    
    HOME_DEVICE_MODE: str = "SIMULATED"
    MQTT_BROKER_URL: str = "mqtt://localhost:1883"
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None
    ESP32_GATEWAY_URL: str = "http://192.168.1.100"
    
    DESKTOP_AGENT_URL: str = "http://localhost:8000"
    DESKTOP_AGENT_TOKEN: str = "holmev_desktop_agent_secure_token"
    
    VISION_CAMERA_INDEX: int = 0
    GESTURE_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
