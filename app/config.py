import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.password_policy import validate_secure_password


class LLMEndpoint(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str
    api_key: str = Field(repr=False)
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not re.fullmatch(r"https?://[^\s]+", normalized):
            raise ValueError("LLM endpoint base_url must be an HTTP(S) URL")
        return normalized


class LLMEndpointFileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str
    api_key: SecretStr | None = Field(default=None, repr=False)
    api_key_env: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z_][A-Z0-9_]*$",
    )
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False

    @model_validator(mode="after")
    def validate_api_key_source(self) -> "LLMEndpointFileEntry":
        if (self.api_key is None) == (self.api_key_env is None):
            raise ValueError("Configure exactly one of api_key or api_key_env")
        return self

    def resolve(self) -> LLMEndpoint:
        if self.api_key_env is not None:
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise ValueError(
                    f"Environment variable {self.api_key_env} is required by LLM endpoint {self.key}"
                )
        else:
            assert self.api_key is not None
            api_key = self.api_key.get_secret_value()
        return LLMEndpoint(
            key=self.key,
            display_name=self.display_name,
            base_url=self.base_url,
            api_key=api_key,
            model=self.model,
            supports_vision=self.supports_vision,
        )


class LLMConfiguration(BaseModel):
    default_endpoint: str = Field(min_length=1, max_length=64)
    endpoints: list[LLMEndpoint]

    @model_validator(mode="after")
    def validate_endpoint_keys(self) -> "LLMConfiguration":
        endpoint_keys = [endpoint.key for endpoint in self.endpoints]
        if not endpoint_keys:
            raise ValueError("LLM endpoint configuration must contain at least one endpoint")
        if len(endpoint_keys) != len(set(endpoint_keys)):
            raise ValueError("LLM endpoint keys must be unique")
        if self.default_endpoint not in endpoint_keys:
            raise ValueError("default_endpoint must match a configured endpoint")
        return self


class LLMConfigurationFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_endpoint: str = Field(min_length=1, max_length=64)
    endpoints: list[LLMEndpointFileEntry]

    def resolve(self) -> LLMConfiguration:
        return LLMConfiguration(
            default_endpoint=self.default_endpoint,
            endpoints=[endpoint.resolve() for endpoint in self.endpoints],
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://rag_user:rag_password@localhost:5433/rag_db"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_request_body_bytes: int = Field(default=51 * 1024 * 1024, ge=1)

    embedding_base_url: str = "http://localhost:8070"
    embedding_model: str = "BAAI/bge-m3"
    reranker_mode: Literal["embedding", "cross_encoder"] = "embedding"
    reranker_base_url: str | None = None


    llm_endpoints_file: Path = Path("config/llm-endpoints.json")
    llm_configuration: LLMConfiguration = Field(exclude=True)
    vision_caption_mode: Literal["disabled", "risk_only", "all_visual"] = "disabled"
    vision_caption_dpi: int = Field(default=144, ge=72, le=200)
    vision_caption_version: str = "gemma4-page-caption-v1"
    readiness_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    log_level: str = "INFO"

    auth_cookie_name: str = "mininblm_session"
    auth_session_ttl_hours: int = Field(default=168, ge=1, le=8760)
    auth_cookie_secure: bool = False
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    @model_validator(mode="before")
    @classmethod
    def load_llm_configuration(cls, values: object) -> object:
        if not isinstance(values, dict) or values.get("llm_configuration") is not None:
            return values
        path = Path(values.get("llm_endpoints_file", "config/llm-endpoints.json")).expanduser()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load LLM endpoint configuration from {path}: {exc}") from exc
        values["llm_configuration"] = LLMConfigurationFile.model_validate(payload).resolve()
        return values

    @field_validator("bootstrap_admin_username", "bootstrap_admin_password", mode="before")
    @classmethod
    def empty_bootstrap_values_are_disabled(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_request_body_limit(self) -> "Settings":
        if self.max_request_body_bytes <= self.max_upload_bytes:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be greater than MAX_UPLOAD_BYTES")
        return self


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

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> "Settings":
        if (
            self.vision_caption_mode != "disabled"
            and not self.get_llm_endpoint().supports_vision
        ):
            raise ValueError("The default LLM endpoint must support vision when captioning is enabled")
        return self

    @property
    def llm_endpoints(self) -> list[LLMEndpoint]:
        return self.llm_configuration.endpoints

    @property
    def llm_default_endpoint(self) -> str:
        return self.llm_configuration.default_endpoint

    def get_llm_endpoint(self, key: str | None = None) -> LLMEndpoint:
        selected_key = key or self.llm_default_endpoint
        for endpoint in self.llm_endpoints:
            if endpoint.key == selected_key:
                return endpoint
        raise KeyError(f"Unknown LLM endpoint: {selected_key}")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
