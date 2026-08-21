import pytest

from app.config import LLMEndpoint
from app.services import language_model_service


@pytest.fixture(autouse=True)
def active_language_model_endpoint():
    """DB·파일 없는 단위 테스트에 고정 endpoint 문맥을 제공한다."""
    endpoint = LLMEndpoint(
        key="unit",
        display_name="Unit test model",
        base_url="http://unit-model:8000/v1",
        api_key="unit-key",
        model="unit-model",
        supports_vision=True,
    )
    with language_model_service.use_endpoint(endpoint):
        yield
