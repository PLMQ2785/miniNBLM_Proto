from functools import lru_cache
import re

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.password_policy import validate_secure_password


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
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    @field_validator("bootstrap_admin_username", "bootstrap_admin_password", mode="before")
    @classmethod
    def empty_bootstrap_values_are_disabled(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_bootstrap_administrator(self) -> "Settings":
        username = self.bootstrap_admin_username
        password = self.bootstrap_admin_password
        if (username is None) != (password is None):
            raise ValueError(
                "BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD must be set together"
            )
        if username is None or password is None:
            return self

        normalized_username = username.strip().casefold()
        if not re.fullmatch(r"[a-z0-9_.-]{3,32}", normalized_username):
            raise ValueError("BOOTSTRAP_ADMIN_USERNAME is invalid")
        validate_secure_password(password, normalized_username)
        self.bootstrap_admin_username = normalized_username
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
