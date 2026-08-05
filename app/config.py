from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://rag_user:rag_password@localhost:5432/rag_db"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)

    embedding_base_url: str = "http://localhost:8070"
    embedding_model: str = "BAAI/bge-m3"

    vllm_base_url: str = "http://localhost:8010/v1"
    vllm_api_key: str = "EMPTY"
    vllm_model: str = "gemma4"
    readiness_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    auth_cookie_name: str = "mininblm_session"
    auth_session_ttl_hours: int = Field(default=168, ge=1, le=8760)
    auth_cookie_secure: bool = False
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
