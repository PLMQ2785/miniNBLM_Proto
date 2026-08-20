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
    """런타임 모델 호출에 필요한 검증된 엔드포인트 설정이다."""
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str
    api_key: str = Field(repr=False)
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """모델 서버 주소를 정규화하고 HTTP 계열만 허용한다."""
        normalized = value.strip().rstrip("/")
        if not re.fullmatch(r"https?://[^\s]+", normalized):
            raise ValueError("LLM endpoint base_url must be an HTTP(S) URL")
        return normalized


class LLMEndpointFileEntry(BaseModel):
    """설정 파일에서 API 키 직접값 또는 환경 변수 참조를 받는다."""
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
        """API 키 출처가 정확히 하나만 지정되었는지 확인한다."""
        if (self.api_key is None) == (self.api_key_env is None):
            raise ValueError("Configure exactly one of api_key or api_key_env")
        return self

    def resolve(self) -> LLMEndpoint:
        """비밀 키 참조를 풀어 런타임 엔드포인트 설정으로 변환한다."""
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
    """런타임에서 사용할 모델 엔드포인트 목록과 기본 선택을 묶는다."""
    default_endpoint: str = Field(min_length=1, max_length=64)
    endpoints: list[LLMEndpoint]

    @model_validator(mode="after")
    def validate_endpoint_keys(self) -> "LLMConfiguration":
        """엔드포인트 키의 존재·고유성과 기본 선택을 검증한다."""
        endpoint_keys = [endpoint.key for endpoint in self.endpoints]
        if not endpoint_keys:
            raise ValueError("LLM endpoint configuration must contain at least one endpoint")
        if len(endpoint_keys) != len(set(endpoint_keys)):
            raise ValueError("LLM endpoint keys must be unique")
        if self.default_endpoint not in endpoint_keys:
            raise ValueError("default_endpoint must match a configured endpoint")
        return self


class LLMConfigurationFile(BaseModel):
    """모델 엔드포인트 JSON 파일의 최상위 입력 경계다."""
    model_config = ConfigDict(extra="forbid")
    default_endpoint: str = Field(min_length=1, max_length=64)
    endpoints: list[LLMEndpointFileEntry]

    def resolve(self) -> LLMConfiguration:
        """파일 입력을 비밀값이 해석된 런타임 설정으로 변환한다."""
        return LLMConfiguration(
            default_endpoint=self.default_endpoint,
            endpoints=[endpoint.resolve() for endpoint in self.endpoints],
        )


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
        """모델 설정 파일 오류를 시작 단계에서 검증해 런타임 우회를 막는다."""
        # 엔드포인트 설정 오류는 런타임 대체 없이 시작 오류로 처리한다.
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

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> "Settings":
        """비전 캡션 사용 시 기본 모델의 이미지 지원을 검증한다."""
        if (
            self.vision_caption_mode != "disabled"
            and not self.get_llm_endpoint().supports_vision
        ):
            raise ValueError("The default LLM endpoint must support vision when captioning is enabled")
        return self

    @property
    def llm_endpoints(self) -> list[LLMEndpoint]:
        """설정된 모델 엔드포인트 목록을 노출한다."""
        return self.llm_configuration.endpoints

    @property
    def llm_default_endpoint(self) -> str:
        """기본 모델 엔드포인트 키를 노출한다."""
        return self.llm_configuration.default_endpoint

    def get_llm_endpoint(self, key: str | None = None) -> LLMEndpoint:
        """지정 키 또는 기본 키에 해당하는 모델 엔드포인트를 찾는다."""
        selected_key = key or self.llm_default_endpoint
        for endpoint in self.llm_endpoints:
            if endpoint.key == selected_key:
                return endpoint
        raise KeyError(f"Unknown LLM endpoint: {selected_key}")


@lru_cache
def get_settings() -> Settings:
    """프로세스에서 공유할 설정 인스턴스를 한 번만 생성한다."""
    return Settings()


settings = get_settings()
