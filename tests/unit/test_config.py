import pytest
from pydantic import ValidationError

from app.config import LLMConfigurationFile, LLMEndpointFileEntry, Settings


def _endpoint(**overrides) -> dict:
    """파일 계약 검증에 사용할 기본 endpoint 메타데이터를 만든다."""
    payload = {
        "key": "primary",
        "display_name": "Primary",
        "base_url": "https://models.example/v1",
        "authentication": "managed",
        "api_key_ciphertext": "ciphertext-placeholder",
        "model": "model-a",
        "supports_vision": False,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_settings_only_configures_endpoint_and_master_key_paths(tmp_path) -> None:
    """Settings는 endpoint 내용을 캐시하지 않고 registry 경로만 보관한다."""
    endpoint_file = tmp_path / "llm-endpoints.json"
    master_key_file = tmp_path / "master.key"

    configured = Settings(
        _env_file=None,
        llm_endpoints_file=endpoint_file,
        llm_master_key_file=master_key_file,
    )

    assert configured.llm_endpoints_file == endpoint_file
    assert configured.llm_master_key_file == master_key_file


def test_endpoint_file_entry_rejects_ciphertext_for_none_authentication() -> None:
    """인증 없음 endpoint에는 credential 암호문을 저장할 수 없다."""
    with pytest.raises(ValidationError, match="none cannot contain"):
        LLMEndpointFileEntry.model_validate(_endpoint(authentication="none"))


def test_endpoint_file_entry_requires_ciphertext_for_managed_authentication() -> None:
    """관리 endpoint에는 credential 암호문이 필수다."""
    with pytest.raises(ValidationError, match="managed requires"):
        LLMEndpointFileEntry.model_validate(_endpoint(api_key_ciphertext=None))


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
