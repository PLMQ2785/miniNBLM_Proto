from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LanguageModelEndpointWriteRequest(BaseModel):
    """관리자가 저장할 endpoint 메타데이터와 write-only API key다."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    supports_vision: bool = False
    enabled: bool = True
    authentication: Literal["none", "managed"]
    api_key: SecretStr | None = None


class AdminLanguageModelEndpointResponse(BaseModel):
    """실제 credential을 제외하고 관리자에게 공개할 endpoint 상태다."""

    key: str
    display_name: str
    base_url: str
    model: str
    supports_vision: bool
    enabled: bool
    authentication: Literal["none", "managed"]
    api_key_configured: bool
    is_default: bool


class AdminLanguageModelStateResponse(BaseModel):
    """JSON revision과 전체 endpoint를 관리자 화면에 제공한다."""

    revision: str
    default_endpoint_key: str
    reload_error: str | None = None
    endpoints: list[AdminLanguageModelEndpointResponse]
