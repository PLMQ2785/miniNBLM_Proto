import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.password_policy import validate_secure_password


class LLMEndpoint(BaseModel):
    """한 요청이 끝날 때까지 고정해서 사용할 모델 endpoint snapshot이다."""
    model_config = ConfigDict(frozen=True)
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str
    api_key: str = Field(repr=False)
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """모델 서버 주소를 정규화하고 HTTP 계열만 허용한다."""
        normalized = value.strip().rstrip("/")
        if not re.fullmatch(r"https?://[^\s]+", normalized):
            raise ValueError("LLM endpoint base_url must be an HTTP(S) URL")
        return normalized


class LLMEndpointFileEntry(BaseModel):
    """JSON endpoint 메타데이터와 선택적 암호문 credential을 검증한다."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str
    authentication: Literal["none", "managed"]
    api_key_ciphertext: str | None = Field(default=None, min_length=1, max_length=8192, repr=False)
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_authentication(self) -> "LLMEndpointFileEntry":
        """인증 없음에는 암호문을 금지하고 managed 인증에는 필수화한다."""
        if self.authentication == "none" and self.api_key_ciphertext is not None:
            raise ValueError("authentication none cannot contain an API key ciphertext")
        if self.authentication == "managed" and self.api_key_ciphertext is None:
            raise ValueError("authentication managed requires an API key ciphertext")
        return self

    def resolve(self, api_key: str) -> LLMEndpoint:
        """복호화된 credential을 호출 가능한 immutable snapshot에만 결합한다."""
        return LLMEndpoint(
            key=self.key,
            display_name=self.display_name,
            base_url=self.base_url,
            api_key=api_key,
            model=self.model,
            supports_vision=self.supports_vision,
            enabled=self.enabled,
        )


class LLMConfigurationFile(BaseModel):
    """핫 리로드와 관리자 수정의 유일한 endpoint JSON 계약이다."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    default_endpoint: str = Field(min_length=1, max_length=64)
    endpoints: tuple[LLMEndpointFileEntry, ...]

    @model_validator(mode="after")
    def validate_endpoint_keys(self) -> "LLMConfigurationFile":
        """endpoint key의 고유성과 활성 기본 endpoint 존재를 검증한다."""
        if not self.endpoints:
            raise ValueError("LLM endpoint configuration must contain at least one endpoint")
        endpoint_keys = [endpoint.key for endpoint in self.endpoints]
        if len(endpoint_keys) != len(set(endpoint_keys)):
            raise ValueError("LLM endpoint keys must be unique")
        default = self.get_endpoint(self.default_endpoint)
        if default is None:
            raise ValueError("default_endpoint must match a configured endpoint")
        if not default.enabled:
            raise ValueError("default_endpoint must be enabled")
        return self

    def get_endpoint(self, key: str) -> LLMEndpointFileEntry | None:
        """지정 key의 파일 endpoint를 반환한다."""
        return next((endpoint for endpoint in self.endpoints if endpoint.key == key), None)


class Settings(BaseSettings):
    """환경 변수와 설정 파일을 합쳐 애플리케이션 실행값을 제공한다."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://rag_user:rag_password@localhost:5433/rag_db"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_request_body_bytes: int = Field(default=51 * 1024 * 1024, ge=1)

    embedding_base_url: str = "http://localhost:8070"
    embedding_model: str = "BAAI/bge-m3"


    llm_endpoints_file: Path = Path("config/llm-endpoints.json")
    llm_master_key_file: Path = Path("data/secrets/llm/master.key")
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


    @field_validator("bootstrap_admin_username", "bootstrap_admin_password", mode="before")
    @classmethod
    def empty_bootstrap_values_are_disabled(cls, value: object) -> object:
        """빈 부트스트랩 관리자 값을 미설정 상태로 정규화한다."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_request_body_limit(self) -> "Settings":
        """멀티파트 여유 공간을 포함하도록 요청 제한을 검증한다."""
        # 원본 PDF 외 멀티파트 메타데이터가 들어갈 여유가 필요하다.
        if self.max_request_body_bytes <= self.max_upload_bytes:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be greater than MAX_UPLOAD_BYTES")
        return self

    @model_validator(mode="after")
    def validate_bootstrap_administrator(self) -> "Settings":
        """부트스트랩 관리자 자격 증명의 쌍과 보안 정책을 검증한다."""
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
    """프로세스에서 공유할 설정 인스턴스를 한 번만 생성한다."""
    return Settings()


settings = get_settings()
