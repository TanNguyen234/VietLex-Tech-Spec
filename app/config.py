from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyHttpUrl
from typing import Optional
from functools import lru_cache

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Qdrant Database
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    
    # Cohere API
    COHERE_API_KEY: Optional[str] = None
    
    # LLM Gateway (OmniGate)
    OMNIGATE_BASE_URL: str = "https://llmgateway.onrender.com"
    LITELLM_MASTER_KEY: str = "default_litellm_master_key"
    
    # Logfire Token
    LOGFIRE_TOKEN: Optional[str] = None
    
    # MongoDB Connection URL
    MONGO_URL: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
