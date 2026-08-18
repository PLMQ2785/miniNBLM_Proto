import pytest
from pydantic import ValidationError

from app.clients import llm_client
from app.clients.llm_client import LLMClient
from app.services import language_model_service
from app.config import LLMConfiguration, Settings


def _settings(*, default: str = "primary", vision_mode: str = "disabled") -> Settings:
    return Settings(
        _env_file=None,
        llm_configuration=LLMConfiguration(
            default_endpoint=default,
            endpoints=[
                {
                    "key": "primary",
                    "display_name": "Primary text model",
                    "base_url": "http://model-a:8000/v1/",
                    "api_key": "key-a",
                    "model": "model-a",
                    "supports_vision": False,
                },
                {
                    "key": "vision",
                    "display_name": "Vision model",
                    "base_url": "http://model-b:9000/v1",
                    "api_key": "key-b",
                    "model": "model-b",
                    "supports_vision": True,
                },
            ],
        ),
        vision_caption_mode=vision_mode,
    )


def test_client_selects_configured_endpoint_by_key(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(llm_client, "settings", _settings())
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient("vision")

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"
    assert client.model == "model-b"
    assert client.supports_vision is True

def test_client_uses_runtime_active_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = _settings()
    created: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(
        language_model_service,
        "get_active_endpoint",
        lambda: configured.get_llm_endpoint("vision"),
    )
    monkeypatch.setattr(llm_client, "get_active_endpoint", language_model_service.get_active_endpoint)
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient()

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"


def test_default_endpoint_must_exist() -> None:
    with pytest.raises(ValidationError, match="default_endpoint"):
        _settings(default="missing")


def test_captioning_requires_vision_capable_default_endpoint() -> None:
    with pytest.raises(ValidationError, match="must support vision"):
        _settings(vision_mode="risk_only")

    configured = _settings(default="vision", vision_mode="risk_only")
    assert configured.get_llm_endpoint().key == "vision"
