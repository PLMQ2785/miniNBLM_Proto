import stat
import subprocess
from pathlib import Path


ENTRYPOINT = Path(__file__).parents[2] / "docker" / "all-in-one-entrypoint.sh"


def _initialize(active: Path, default: Path) -> subprocess.CompletedProcess[str]:
    """entrypoint의 persisted LLM 설정 초기화 함수만 격리 실행한다."""
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; initialize_llm_config "$2" "$3"',
            "entrypoint-test",
            str(ENTRYPOINT),
            str(active),
            str(default),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_empty_persisted_configuration_is_restored_from_image_default(tmp_path: Path) -> None:
    """기존 volume의 0-byte 설정은 정상 기본 JSON으로 복구한다."""
    active = tmp_path / "data" / "config" / "llm-endpoints.json"
    active.parent.mkdir(parents=True)
    active.write_text("", encoding="utf-8")
    default = tmp_path / "llm-endpoints.default.json"
    default.write_text('{"default_endpoint":"primary","endpoints":[]}\n', encoding="utf-8")

    result = _initialize(active, default)

    assert active.read_bytes() == default.read_bytes()
    assert stat.S_IMODE(active.stat().st_mode) == 0o600
    assert "기본 언어모델 설정을 생성했습니다" in result.stdout


def test_nonempty_operator_configuration_is_never_overwritten(tmp_path: Path) -> None:
    """내용이 있는 운영자 설정은 이미지 기본값보다 항상 우선한다."""
    active = tmp_path / "llm-endpoints.json"
    active.write_text('{"operator":true}\n', encoding="utf-8")
    default = tmp_path / "llm-endpoints.default.json"
    default.write_text('{"default":true}\n', encoding="utf-8")

    result = _initialize(active, default)

    assert active.read_text(encoding="utf-8") == '{"operator":true}\n'
    assert result.stdout == ""
