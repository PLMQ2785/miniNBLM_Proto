import json

import httpx
import pytest

from app.config import LLMEndpoint
from app.services import language_model_service
from app.services.language_model_service import LanguageModelEndpointUnavailableError
from app.services.language_model_registry import LanguageModelRegistry


def _endpoint() -> LLMEndpoint:
    """endpoint 연결 검증에 사용할 snapshot을 만든다."""
    return LLMEndpoint(
        key="secondary",
        display_name="Secondary",
        base_url="http://secondary:8000/v1",
        api_key="key-b",
        model="model-b",
        supports_vision=True,
    )


def test_endpoint_verification_requires_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """endpoint 검증은 snapshot의 model과 인증 정보를 기준으로 요청한다."""
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

    monkeypatch.setattr(language_model_service.httpx, "get", fake_get)

    language_model_service.verify_endpoint(_endpoint())

    assert called["url"] == "http://secondary:8000/v1/models"
    assert called["headers"] == {"Authorization": "Bearer key-b"}


def test_endpoint_verification_rejects_wrong_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """endpoint가 설정 model을 제공하지 않으면 사용 불가로 처리한다."""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8000/v1/models"),
        json={"data": [{"id": "another-model"}]},
    )
    monkeypatch.setattr(language_model_service.httpx, "get", lambda *args, **kwargs: response)

    with pytest.raises(LanguageModelEndpointUnavailableError, match="does not serve"):
        language_model_service.verify_endpoint(_endpoint())


def test_request_context_keeps_endpoint_after_json_reload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """진행 중 요청은 JSON이 바뀌어도 시작 시점 snapshot을 유지한다."""
    monkeypatch.setenv("PRIMARY_API_KEY", "key-a")
    endpoint_file = tmp_path / "llm-endpoints.json"
    original = {
        "default_endpoint": "primary",
        "endpoints": [
            {
                "key": "primary",
                "display_name": "Primary",
                "base_url": "http://primary:8000/v1",
                "api_key_env": "PRIMARY_API_KEY",
                "model": "model-a",
            }
        ],
    }
    endpoint_file.write_text(json.dumps(original), encoding="utf-8")
    registry = LanguageModelRegistry(endpoint_file, tmp_path / "secrets")
    before = registry.initialize()
    monkeypatch.setattr(language_model_service, "registry", registry)

    with language_model_service.use_endpoint(before.default_endpoint):
        changed = {
            **original,
            "endpoints": [
                {
                    **original["endpoints"][0],
                    "base_url": "http://replacement:9000/v1",
                }
            ],
        }
        endpoint_file.write_text(json.dumps(changed), encoding="utf-8")
        registry.snapshot()
        active_during_request = language_model_service.get_active_endpoint()

    assert active_during_request.base_url == "http://primary:8000/v1"
    assert registry.snapshot().default_endpoint.base_url == "http://replacement:9000/v1"
