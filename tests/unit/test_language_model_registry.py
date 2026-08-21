import json
import stat

import pytest

from app.config import LLMConfigurationFile
from app.services.language_model_registry import (
    LanguageModelConfigurationConflictError,
    LanguageModelConfigurationError,
    LanguageModelRegistry,
)


def _configuration(*, base_url: str = "http://primary:8000/v1", include_secondary: bool = False) -> dict:
    """registry 검증에 사용할 endpoint JSON payload를 만든다."""
    endpoints = [
        {
            "key": "primary",
            "display_name": "Primary",
            "base_url": base_url,
            "api_key_env": "PRIMARY_API_KEY",
            "model": "model-a",
            "supports_vision": True,
            "enabled": True,
        }
    ]
    if include_secondary:
        endpoints.append(
            {
                "key": "secondary",
                "display_name": "Secondary",
                "base_url": "http://secondary:9000/v1",
                "api_key_file": "secondary-api-key",
                "model": "model-b",
                "supports_vision": False,
                "enabled": True,
            }
        )
    return {"default_endpoint": "primary", "endpoints": endpoints}


def _registry(tmp_path, monkeypatch: pytest.MonkeyPatch) -> tuple[LanguageModelRegistry, object, object]:
    """환경변수와 secret 파일이 준비된 registry를 생성한다."""
    monkeypatch.setenv("PRIMARY_API_KEY", "primary-secret")
    endpoint_file = tmp_path / "llm-endpoints.json"
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "secondary-api-key").write_text("secondary-secret\n", encoding="utf-8")
    endpoint_file.write_text(json.dumps(_configuration()), encoding="utf-8")
    return LanguageModelRegistry(endpoint_file, secret_dir), endpoint_file, secret_dir


def test_registry_loads_external_credentials_without_exposing_them_in_json(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON 참조를 환경변수와 secret 파일 값으로 해석한다."""
    registry, endpoint_file, _ = _registry(tmp_path, monkeypatch)
    endpoint_file.write_text(json.dumps(_configuration(include_secondary=True)), encoding="utf-8")

    snapshot = registry.initialize()

    assert snapshot.default_endpoint.api_key == "primary-secret"
    assert snapshot.get_endpoint("secondary").api_key == "secondary-secret"
    assert "primary-secret" not in endpoint_file.read_text(encoding="utf-8")
    assert "secondary-secret" not in endpoint_file.read_text(encoding="utf-8")


def test_registry_lazy_reload_preserves_in_flight_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """파일 변경은 다음 조회에만 반영되고 기존 snapshot 객체는 바뀌지 않는다."""
    registry, endpoint_file, _ = _registry(tmp_path, monkeypatch)
    before = registry.initialize()
    endpoint_file.write_text(
        json.dumps(_configuration(base_url="http://replacement:8100/v1")),
        encoding="utf-8",
    )

    after = registry.snapshot()

    assert before.default_endpoint.base_url == "http://primary:8000/v1"
    assert after.default_endpoint.base_url == "http://replacement:8100/v1"
    assert before.revision != after.revision


def test_invalid_external_change_keeps_last_good_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """잘못된 외부 JSON은 서비스 중 snapshot을 오염시키지 않는다."""
    registry, endpoint_file, _ = _registry(tmp_path, monkeypatch)
    before = registry.initialize()
    endpoint_file.write_text("{broken", encoding="utf-8")

    after = registry.snapshot()

    assert after is before
    assert registry.reload_error is not None


def test_registry_replace_is_atomic_and_rejects_stale_revision(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관리자 저장은 완전한 JSON만 공개하고 stale revision을 거부한다."""
    registry, endpoint_file, _ = _registry(tmp_path, monkeypatch)
    before = registry.initialize()
    original_mode = stat.S_IMODE(endpoint_file.stat().st_mode)
    candidate = LLMConfigurationFile.model_validate(_configuration(include_secondary=True))

    after = registry.replace(candidate, expected_revision=before.revision)

    assert json.loads(endpoint_file.read_text(encoding="utf-8"))["endpoints"][1]["key"] == "secondary"
    assert stat.S_IMODE(endpoint_file.stat().st_mode) == original_mode
    with pytest.raises(LanguageModelConfigurationConflictError):
        registry.replace(candidate, expected_revision=before.revision)
    assert registry.snapshot() is after


def test_secret_file_change_reloads_the_next_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """참조 secret 파일 교체도 endpoint JSON 변경 없이 lazy reload한다."""
    registry, endpoint_file, secret_dir = _registry(tmp_path, monkeypatch)
    endpoint_file.write_text(json.dumps(_configuration(include_secondary=True)), encoding="utf-8")
    before = registry.initialize()
    (secret_dir / "secondary-api-key").write_text("rotated-secret-longer\n", encoding="utf-8")

    after = registry.snapshot()

    assert before.get_endpoint("secondary").api_key == "secondary-secret"
    assert after.get_endpoint("secondary").api_key == "rotated-secret-longer"


def test_registry_rejects_missing_credential_at_startup(tmp_path) -> None:
    """최초 기동에서는 마지막 정상값 없이 누락 credential을 허용하지 않는다."""
    endpoint_file = tmp_path / "llm-endpoints.json"
    endpoint_file.write_text(json.dumps(_configuration()), encoding="utf-8")
    registry = LanguageModelRegistry(endpoint_file, tmp_path / "secrets")

    with pytest.raises(LanguageModelConfigurationError, match="PRIMARY_API_KEY"):
        registry.initialize()
