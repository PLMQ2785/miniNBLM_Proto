import json
import stat

import pytest

from app.config import LLMConfigurationFile
from app.services.language_model_credential_service import LanguageModelCredentialCipher
from app.services.language_model_registry import (
    LanguageModelConfigurationConflictError,
    LanguageModelConfigurationError,
    LanguageModelRegistry,
)


def _configuration(
    *,
    base_url: str = "http://primary:8000/v1",
    primary_authentication: str = "managed",
    primary_ciphertext: str | None = None,
    include_secondary: bool = False,
    secondary_ciphertext: str | None = None,
) -> dict:
    """registry 검증에 사용할 endpoint JSON payload를 만든다."""
    primary = {
        "key": "primary",
        "display_name": "Primary",
        "base_url": base_url,
        "authentication": primary_authentication,
        "model": "model-a",
        "supports_vision": True,
        "enabled": True,
    }
    if primary_authentication == "managed":
        primary["api_key_ciphertext"] = primary_ciphertext
    endpoints = [primary]
    if include_secondary:
        endpoints.append(
            {
                "key": "secondary",
                "display_name": "Secondary",
                "base_url": "http://secondary:9000/v1",
                "authentication": "managed",
                "api_key_ciphertext": secondary_ciphertext,
                "model": "model-b",
                "supports_vision": False,
                "enabled": True,
            }
        )
    return {"default_endpoint": "primary", "endpoints": endpoints}


def _registry(tmp_path) -> tuple[LanguageModelRegistry, object, object, str]:
    """암호화된 primary credential이 준비된 registry를 생성한다."""
    endpoint_file = tmp_path / "llm-endpoints.json"
    master_key_file = tmp_path / "master.key"
    cipher = LanguageModelCredentialCipher(master_key_file)
    primary_ciphertext = cipher.encrypt("primary-key")
    endpoint_file.write_text(
        json.dumps(_configuration(primary_ciphertext=primary_ciphertext)),
        encoding="utf-8",
    )
    return (
        LanguageModelRegistry(endpoint_file, master_key_file),
        endpoint_file,
        master_key_file,
        primary_ciphertext,
    )


def test_registry_loads_encrypted_credentials_without_exposing_them_in_json(tmp_path) -> None:
    """JSON 암호문을 snapshot credential로 복호화하되 평문은 저장하지 않는다."""
    registry, endpoint_file, _, primary_ciphertext = _registry(tmp_path)
    secondary_ciphertext = registry.encrypt_api_key("secondary-key")
    endpoint_file.write_text(
        json.dumps(
            _configuration(
                primary_ciphertext=primary_ciphertext,
                include_secondary=True,
                secondary_ciphertext=secondary_ciphertext,
            )
        ),
        encoding="utf-8",
    )

    snapshot = registry.initialize()

    assert snapshot.default_endpoint.api_key == "primary-key"
    assert snapshot.get_endpoint("secondary").api_key == "secondary-key"
    stored = endpoint_file.read_text(encoding="utf-8")
    assert "primary-key" not in stored
    assert "secondary-key" not in stored


def test_registry_resolves_none_authentication_to_empty(tmp_path) -> None:
    """인증 없음 endpoint는 암호문 없이 EMPTY credential을 사용한다."""
    endpoint_file = tmp_path / "llm-endpoints.json"
    master_key_file = tmp_path / "master.key"
    endpoint_file.write_text(
        json.dumps(_configuration(primary_authentication="none")),
        encoding="utf-8",
    )

    snapshot = LanguageModelRegistry(endpoint_file, master_key_file).initialize()

    assert snapshot.default_endpoint.api_key == "EMPTY"
    assert stat.S_IMODE(master_key_file.stat().st_mode) == 0o600


def test_registry_lazy_reload_preserves_in_flight_snapshot(tmp_path) -> None:
    """파일 변경은 다음 조회에만 반영되고 기존 snapshot 객체는 바뀌지 않는다."""
    registry, endpoint_file, _, primary_ciphertext = _registry(tmp_path)
    before = registry.initialize()
    endpoint_file.write_text(
        json.dumps(
            _configuration(
                base_url="http://replacement:8100/v1",
                primary_ciphertext=primary_ciphertext,
            )
        ),
        encoding="utf-8",
    )

    after = registry.snapshot()

    assert before.default_endpoint.base_url == "http://primary:8000/v1"
    assert after.default_endpoint.base_url == "http://replacement:8100/v1"
    assert before.revision != after.revision


def test_invalid_external_change_keeps_last_good_snapshot(tmp_path) -> None:
    """잘못된 외부 JSON은 서비스 중 snapshot을 오염시키지 않는다."""
    registry, endpoint_file, _, _ = _registry(tmp_path)
    before = registry.initialize()
    endpoint_file.write_text("{broken", encoding="utf-8")

    after = registry.snapshot()

    assert after is before
    assert registry.reload_error is not None


def test_invalid_credential_change_keeps_last_good_snapshot(tmp_path) -> None:
    """복호화 실패를 일으키는 JSON 변경은 마지막 정상 snapshot을 유지한다."""
    registry, endpoint_file, _, primary_ciphertext = _registry(tmp_path)
    before = registry.initialize()
    endpoint_file.write_text(
        json.dumps(
            _configuration(
                primary_ciphertext="invalid-ciphertext",
            )
        ),
        encoding="utf-8",
    )

    after = registry.snapshot()

    assert after is before
    assert after.default_endpoint.api_key == "primary-key"
    assert registry.reload_error is not None


def test_registry_replace_is_atomic_and_rejects_stale_revision(tmp_path) -> None:
    """관리자 저장은 완전한 JSON만 공개하고 stale revision을 거부한다."""
    registry, endpoint_file, _, primary_ciphertext = _registry(tmp_path)
    before = registry.initialize()
    original_mode = stat.S_IMODE(endpoint_file.stat().st_mode)
    secondary_ciphertext = registry.encrypt_api_key("secondary-key")
    candidate = LLMConfigurationFile.model_validate(
        _configuration(
            primary_ciphertext=primary_ciphertext,
            include_secondary=True,
            secondary_ciphertext=secondary_ciphertext,
        )
    )

    after = registry.replace(candidate, expected_revision=before.revision)

    assert json.loads(endpoint_file.read_text(encoding="utf-8"))["endpoints"][1]["key"] == "secondary"
    assert stat.S_IMODE(endpoint_file.stat().st_mode) == original_mode
    with pytest.raises(LanguageModelConfigurationConflictError):
        registry.replace(candidate, expected_revision=before.revision)
    assert registry.snapshot() is after


def test_encrypted_credential_change_reloads_the_next_snapshot(tmp_path) -> None:
    """JSON 암호문 교체는 다음 snapshot에 반영된다."""
    registry, endpoint_file, _, primary_ciphertext = _registry(tmp_path)
    secondary_ciphertext = registry.encrypt_api_key("secondary-key")
    endpoint_file.write_text(
        json.dumps(
            _configuration(
                primary_ciphertext=primary_ciphertext,
                include_secondary=True,
                secondary_ciphertext=secondary_ciphertext,
            )
        ),
        encoding="utf-8",
    )
    before = registry.initialize()
    rotated_ciphertext = registry.encrypt_api_key("rotated-secondary-key")
    endpoint_file.write_text(
        json.dumps(
            _configuration(
                primary_ciphertext=primary_ciphertext,
                include_secondary=True,
                secondary_ciphertext=rotated_ciphertext,
            )
        ),
        encoding="utf-8",
    )

    after = registry.snapshot()

    assert before.get_endpoint("secondary").api_key == "secondary-key"
    assert after.get_endpoint("secondary").api_key == "rotated-secondary-key"


def test_registry_rejects_missing_master_key_with_existing_ciphertext(tmp_path) -> None:
    """최초 기동에서는 암호문이 있는데 master key가 없으면 fail closed 한다."""
    _, endpoint_file, master_key_file, _ = _registry(tmp_path)
    master_key_file.unlink()

    with pytest.raises(LanguageModelConfigurationError, match="master key is missing"):
        LanguageModelRegistry(endpoint_file, master_key_file).initialize()


def test_runtime_master_key_loss_keeps_last_good_snapshot(tmp_path) -> None:
    """실행 중 master key가 사라지면 새 설정 대신 마지막 정상 snapshot을 유지한다."""
    registry, _, master_key_file, _ = _registry(tmp_path)
    before = registry.initialize()
    master_key_file.unlink()

    after = registry.snapshot()

    assert after is before
    assert after.default_endpoint.api_key == "primary-key"
    assert registry.reload_error is not None
