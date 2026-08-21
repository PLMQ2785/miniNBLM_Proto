from pydantic import BaseModel, ConfigDict, Field, model_validator


class LanguageModelEndpointWriteRequest(BaseModel):
    """관리자가 JSON에 저장할 endpoint 메타데이터와 credential 참조다."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key_env: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z_][A-Z0-9_]*$",
    )
    api_key_file: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_credential_reference(self) -> "LanguageModelEndpointWriteRequest":
        """환경변수와 secret 파일 참조 중 하나만 허용한다."""
        if (self.api_key_env is None) == (self.api_key_file is None):
            raise ValueError("Configure exactly one of api_key_env or api_key_file")
        return self


class AdminLanguageModelEndpointResponse(BaseModel):
    """실제 credential을 제외하고 관리자에게 공개할 endpoint 상태다."""

    key: str
    display_name: str
    base_url: str
    model: str
    supports_vision: bool
    enabled: bool
    credential_source: str
    credential_reference: str
    is_default: bool


class AdminLanguageModelStateResponse(BaseModel):
    """JSON revision과 전체 endpoint를 관리자 화면에 제공한다."""

    revision: str
    default_endpoint_key: str
    reload_error: str | None = None
    endpoints: list[AdminLanguageModelEndpointResponse]
