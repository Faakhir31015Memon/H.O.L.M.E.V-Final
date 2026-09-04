import os
from typing import Optional

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
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
except ImportError:
    from pydantic import BaseModel
    class Settings(BaseModel):
        ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
        DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
        LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
        
        JWT_SECRET: str = os.getenv("JWT_SECRET", "holmev_production_super_secret_jwt_key_change_me_in_prod")
        SECRET_KEY: str = os.getenv("SECRET_KEY", "holmev_system_secret_key_3115")
        ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
        
        DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./holmev.db")
        REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
        GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
        DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
        DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "gemini")
        AI_FALLBACK_PROVIDER: str = os.getenv("AI_FALLBACK_PROVIDER", "openai")
        
        STT_PROVIDER: str = os.getenv("STT_PROVIDER", "local")
        TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "local")
        CUSTOM_VOICE_PROVIDER: str = os.getenv("CUSTOM_VOICE_PROVIDER", "local")
        CUSTOM_VOICE_ID: str = os.getenv("CUSTOM_VOICE_ID", "holmev_voice_prime")
        
        HOME_DEVICE_MODE: str = os.getenv("HOME_DEVICE_MODE", "SIMULATED")
        MQTT_BROKER_URL: str = os.getenv("MQTT_BROKER_URL", "mqtt://localhost:1883")
        MQTT_USERNAME: Optional[str] = os.getenv("MQTT_USERNAME")
        MQTT_PASSWORD: Optional[str] = os.getenv("MQTT_PASSWORD")
        ESP32_GATEWAY_URL: str = os.getenv("ESP32_GATEWAY_URL", "http://192.168.1.100")
        
        DESKTOP_AGENT_URL: str = os.getenv("DESKTOP_AGENT_URL", "http://localhost:8000")
        DESKTOP_AGENT_TOKEN: str = os.getenv("DESKTOP_AGENT_TOKEN", "holmev_desktop_agent_secure_token")
        
        VISION_CAMERA_INDEX: int = int(os.getenv("VISION_CAMERA_INDEX", "0"))
        GESTURE_ENABLED: bool = os.getenv("GESTURE_ENABLED", "true").lower() == "true"

settings = Settings()
