import json

import pytest
from pydantic import ValidationError

from app.config import Settings


def _write_configuration(tmp_path, payload: dict) -> str:
    """테스트용 모델 엔드포인트 설정 파일을 기록한다."""
    path = tmp_path / "llm-endpoints.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_settings_load_language_models_from_json_file(tmp_path) -> None:
    """JSON 파일의 기본 엔드포인트와 모델 설정을 불러온다."""
    path = _write_configuration(
        tmp_path,
        {
            "default_endpoint": "primary",
            "endpoints": [
                {
                    "key": "primary",
                    "display_name": "Primary",
                    "base_url": "https://models.example/v1/",
                    "api_key": "literal-test-key",
                    "model": "model-a",
                    "supports_vision": False,
                }
            ],
        },
    )

    configured = Settings(_env_file=None, llm_endpoints_file=path)

    assert configured.llm_default_endpoint == "primary"
    assert configured.get_llm_endpoint().base_url == "https://models.example/v1"
    assert configured.get_llm_endpoint().api_key == "literal-test-key"


def test_settings_resolve_endpoint_api_key_from_environment(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """환경 변수로 지정한 엔드포인트 API 키를 실제 값으로 해석한다."""
    monkeypatch.setenv("REMOTE_MODEL_API_KEY", "secret-from-environment")
    path = _write_configuration(
        tmp_path,
        {
            "default_endpoint": "remote",
            "endpoints": [
                {
                    "key": "remote",
                    "display_name": "Remote",
                    "base_url": "https://models.example/v1",
                    "api_key_env": "REMOTE_MODEL_API_KEY",
                    "model": "remote-model",
                    "supports_vision": True,
                }
            ],
        },
    )

    configured = Settings(_env_file=None, llm_endpoints_file=path)

    assert configured.get_llm_endpoint().api_key == "secret-from-environment"


def test_settings_reject_missing_api_key_environment_variable(tmp_path) -> None:
    """API 키 환경 변수가 없으면 설정 로드를 거부한다."""
    path = _write_configuration(
        tmp_path,
        {
            "default_endpoint": "remote",
            "endpoints": [
                {
                    "key": "remote",
                    "display_name": "Remote",
                    "base_url": "https://models.example/v1",
                    "api_key_env": "MISSING_REMOTE_MODEL_API_KEY",
                    "model": "remote-model",
                }
            ],
        },
    )

    with pytest.raises(ValidationError, match="MISSING_REMOTE_MODEL_API_KEY"):
        Settings(_env_file=None, llm_endpoints_file=path)


def test_settings_reject_invalid_default_endpoint_in_file(tmp_path) -> None:
    """등록되지 않은 기본 엔드포인트를 가리키는 설정은 거부한다."""
    path = _write_configuration(
        tmp_path,
        {
            "default_endpoint": "missing",
            "endpoints": [
                {
                    "key": "primary",
                    "display_name": "Primary",
                    "base_url": "http://127.0.0.1:8010/v1",
                    "api_key": "EMPTY",
                    "model": "primary",
                }
            ],
        },
    )

    with pytest.raises(ValidationError, match="default_endpoint"):
        Settings(_env_file=None, llm_endpoints_file=path)


def test_settings_reject_unknown_endpoint_fields(tmp_path) -> None:
    """오타를 포함한 알 수 없는 엔드포인트 필드는 허용하지 않는다."""
    path = _write_configuration(
        tmp_path,
        {
            "default_endpoint": "primary",
            "endpoints": [
                {
                    "key": "primary",
                    "display_name": "Primary",
                    "base_url": "http://127.0.0.1:8010/v1",
                    "api_key": "EMPTY",
                    "model": "primary",
                    "supports_vison": True,
                }
            ],
        },
    )

    with pytest.raises(ValidationError, match="supports_vison"):
        Settings(_env_file=None, llm_endpoints_file=path)
