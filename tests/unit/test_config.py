import pytest
from pydantic import ValidationError

from app.config import LLMConfigurationFile, LLMEndpointFileEntry, Settings


def _endpoint(**overrides) -> dict:
    """파일 계약 검증에 사용할 기본 endpoint 메타데이터를 만든다."""
    payload = {
        "key": "primary",
        "display_name": "Primary",
        "base_url": "https://models.example/v1",
        "api_key_env": "PRIMARY_API_KEY",
        "model": "model-a",
        "supports_vision": False,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_settings_only_configures_endpoint_and_secret_paths(tmp_path) -> None:
    """Settings는 endpoint 내용을 캐시하지 않고 registry 경로만 보관한다."""
    endpoint_file = tmp_path / "llm-endpoints.json"
    secret_dir = tmp_path / "secrets"

    configured = Settings(
        _env_file=None,
        llm_endpoints_file=endpoint_file,
        llm_secrets_dir=secret_dir,
    )

    assert configured.llm_endpoints_file == endpoint_file
    assert configured.llm_secrets_dir == secret_dir


def test_endpoint_file_entry_rejects_inline_credential() -> None:
    """endpoint JSON에 실제 credential 값을 직접 저장하지 못하게 한다."""
    payload = _endpoint(api_key="literal-secret")
    payload.pop("api_key_env")

    with pytest.raises(ValidationError, match="api_key"):
        LLMEndpointFileEntry.model_validate(payload)


def test_endpoint_file_entry_requires_one_credential_reference() -> None:
    """환경변수와 secret 파일 참조를 동시에 지정하지 못하게 한다."""
    with pytest.raises(ValidationError, match="exactly one"):
        LLMEndpointFileEntry.model_validate(
            _endpoint(api_key_file="primary-api-key")
        )


def test_configuration_rejects_missing_or_disabled_default() -> None:
    """기본 endpoint는 JSON에 존재하며 활성 상태여야 한다."""
    with pytest.raises(ValidationError, match="default_endpoint"):
        LLMConfigurationFile.model_validate(
            {"default_endpoint": "missing", "endpoints": [_endpoint()]}
        )

    with pytest.raises(ValidationError, match="enabled"):
        LLMConfigurationFile.model_validate(
            {
                "default_endpoint": "primary",
                "endpoints": [_endpoint(enabled=False)],
            }
        )


def test_configuration_rejects_unknown_endpoint_fields() -> None:
    """오타가 포함된 endpoint 필드를 허용하지 않는다."""
    with pytest.raises(ValidationError, match="supports_vison"):
        LLMConfigurationFile.model_validate(
            {
                "default_endpoint": "primary",
                "endpoints": [_endpoint(supports_vison=True)],
            }
        )
