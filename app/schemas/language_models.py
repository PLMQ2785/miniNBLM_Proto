from pydantic import BaseModel


class LanguageModelEndpointResponse(BaseModel):
    key: str
    display_name: str
    model: str
    supports_vision: bool


class LanguageModelStateResponse(BaseModel):
    endpoints: list[LanguageModelEndpointResponse]
    active_endpoint_key: str
