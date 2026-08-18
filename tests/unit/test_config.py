import json

import pytest
from pydantic import ValidationError

from app.config import Settings


def _write_configuration(tmp_path, payload: dict) -> str:
    path = tmp_path / "llm-endpoints.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_settings_load_language_models_from_json_file(tmp_path) -> None:
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
