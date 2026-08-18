import httpx
import pytest

from app.config import LLMConfiguration, Settings
from app.services import language_model_service
from app.services.language_model_service import LanguageModelEndpointUnavailableError


def _settings() -> Settings:
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
    configured = _settings()
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8000/v1/models"),
        json={"data": [{"id": "model-b"}]},
    )
    called = {}

    def fake_get(url, **kwargs):
        called.update(url=url, **kwargs)
        return response

    monkeypatch.setattr(language_model_service, "settings", configured)
    monkeypatch.setattr(language_model_service.httpx, "get", fake_get)

    language_model_service._verify_endpoint(configured.get_llm_endpoint("secondary"))

    assert called["url"] == "http://secondary:8000/v1/models"
    assert called["headers"] == {"Authorization": "Bearer key-b"}


def test_endpoint_verification_rejects_wrong_model(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = _settings()
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8000/v1/models"),
        json={"data": [{"id": "another-model"}]},
    )
    monkeypatch.setattr(language_model_service.httpx, "get", lambda *args, **kwargs: response)

    with pytest.raises(LanguageModelEndpointUnavailableError, match="does not serve"):
        language_model_service._verify_endpoint(configured.get_llm_endpoint("secondary"))
