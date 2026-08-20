import httpx
import pytest

from app.config import LLMConfiguration, Settings
from app.services import language_model_service
from app.services.language_model_service import LanguageModelEndpointUnavailableError


def _settings() -> Settings:
    """엔드포인트 검증에 사용할 다중 모델 설정을 만든다."""
    return Settings(
        _env_file=None,
        llm_configuration=LLMConfiguration(
            default_endpoint="primary",
            endpoints=[
                {
                    "key": "primary",
                    "display_name": "Primary",
                    "base_url": "http://primary:8000/v1",
                    "api_key": "key-a",
                    "model": "model-a",
                    "supports_vision": False,
                },
                {
                    "key": "secondary",
                    "display_name": "Secondary",
                    "base_url": "http://secondary:8000/v1",
                    "api_key": "key-b",
                    "model": "model-b",
                    "supports_vision": True,
                },
            ],
        ),
    )


def test_endpoint_verification_requires_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """엔드포인트 검증은 선택한 모델과 인증 정보를 기준으로 요청한다."""
    configured = _settings()
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8000/v1/models"),
        json={"data": [{"id": "model-b"}]},
    )
    called = {}

    def fake_get(url, **kwargs):
        """검증 요청 인자를 기록하고 준비된 모델 목록을 반환한다."""
        called.update(url=url, **kwargs)
        return response

    monkeypatch.setattr(language_model_service, "settings", configured)
    monkeypatch.setattr(language_model_service.httpx, "get", fake_get)

    language_model_service._verify_endpoint(configured.get_llm_endpoint("secondary"))

    assert called["url"] == "http://secondary:8000/v1/models"
    assert called["headers"] == {"Authorization": "Bearer key-b"}


def test_endpoint_verification_rejects_wrong_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """엔드포인트가 설정 모델을 제공하지 않으면 사용 불가로 처리한다."""
    configured = _settings()
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8000/v1/models"),
        json={"data": [{"id": "another-model"}]},
    )
    monkeypatch.setattr(language_model_service.httpx, "get", lambda *args, **kwargs: response)

    with pytest.raises(LanguageModelEndpointUnavailableError, match="does not serve"):
        language_model_service._verify_endpoint(configured.get_llm_endpoint("secondary"))
