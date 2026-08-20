from pydantic import BaseModel


class LanguageModelEndpointResponse(BaseModel):
    """언어 모델 API가 노출하는 엔드포인트 정보 경계다."""
    key: str
    display_name: str
    model: str
    supports_vision: bool


class LanguageModelStateResponse(BaseModel):
    """언어 모델 API가 반환하는 선택 가능·활성 상태 경계다."""
    endpoints: list[LanguageModelEndpointResponse]
    active_endpoint_key: str
