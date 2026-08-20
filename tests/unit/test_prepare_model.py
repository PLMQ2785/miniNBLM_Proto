import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "docker" / "prepare-model.sh"


def _create_model_archive(tmp_path: Path) -> tuple[Path, str]:
    """설치 테스트에 쓸 최소 모델 압축 파일과 해시를 만든다."""
    source = tmp_path / "source" / "model-release"
    source.mkdir(parents=True)
    (source / "config.json").write_text('{"model_type":"test"}', encoding="utf-8")
    (source / "model.safetensors").write_bytes(b"test-weights")
    archive = tmp_path / "model.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=source.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest


def _run_prepare(
    tmp_path: Path,
    archive: Path | None,
    digest: str,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """격리된 경로와 환경 변수로 모델 준비 스크립트를 실행한다."""
    env = os.environ.copy()
    env.update(
        {
            "VLLM_MODEL_PATH": str(tmp_path / "data" / "models" / "gemma4"),
            "MODEL_CACHE_DIR": str(tmp_path / "data" / "model-cache"),
            "MODEL_ARCHIVE_URL": archive.as_uri() if archive else "",
            "MODEL_ARCHIVE_SHA256": digest,
            "MODEL_KEEP_ARCHIVE": "false",
        }
    )
    env.update(env_overrides or {})
    return subprocess.run(
        [str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_prepare_model_downloads_verifies_and_installs_atomically(tmp_path: Path) -> None:
    """모델을 검증한 뒤 임시 흔적 없이 원자적으로 설치한다."""
    archive, digest = _create_model_archive(tmp_path)

    result = _run_prepare(tmp_path, archive, digest)

    model_path = tmp_path / "data" / "models" / "gemma4"
    assert result.returncode == 0, result.stderr
    assert (model_path / "config.json").is_file()
    assert (model_path / "model.safetensors").read_bytes() == b"test-weights"
    assert (model_path / ".mininblm-model.sha256").read_text().strip() == digest
    assert (
        model_path / ".mininblm-model.source"
    ).read_text().strip() == f"archive:sha256:{digest}"
    assert not list((tmp_path / "data" / "model-cache").glob("*.archive"))
    assert not list((tmp_path / "data" / "models").glob(".gemma4.*"))


def test_prepare_model_reuses_complete_model_without_downloading(tmp_path: Path) -> None:
    """완료 표식이 있는 모델은 원본 없이도 다시 내려받지 않는다."""
    archive, digest = _create_model_archive(tmp_path)
    assert _run_prepare(tmp_path, archive, digest).returncode == 0
    archive.unlink()

    result = _run_prepare(tmp_path, archive, digest)

    assert result.returncode == 0, result.stderr
    assert "모델 cache 준비 완료" in result.stdout


def test_prepare_model_rejects_bad_checksum_without_partial_install(tmp_path: Path) -> None:
    """체크섬 불일치 시 부분 모델과 다운로드 조각을 남기지 않는다."""
    archive, _ = _create_model_archive(tmp_path)

    result = _run_prepare(tmp_path, archive, "0" * 64)

    assert result.returncode != 0
    assert "SHA-256 checksum이 일치하지 않습니다" in result.stderr
    assert not (tmp_path / "data" / "models" / "gemma4").exists()
    assert not list((tmp_path / "data" / "model-cache").glob("*.part"))


def test_prepare_model_retries_with_doh_after_dns_failure(tmp_path: Path) -> None:
    """일반 DNS 다운로드 실패 시 DNS-over-HTTPS로 한 번 재시도한다."""
    archive, digest = _create_model_archive(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    arguments = tmp_path / "curl-arguments"
    real_curl = shutil.which("curl")
    assert real_curl is not None
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> {arguments}
attempt="$(wc -l < {arguments})"
if [[ "$attempt" -eq 1 ]]; then
  exit 6
fi
exec {real_curl} "$@"
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    result = _run_prepare(
        tmp_path,
        archive,
        digest,
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    calls = arguments.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2
    assert "--doh-url https://dns.google/dns-query" in calls[1]
    assert "--resolve dns.google:443:8.8.8.8" in calls[1]
    assert "DNS-over-HTTPS로 재시도합니다" in result.stderr


def test_prepare_model_downloads_pinned_hugging_face_snapshot(tmp_path: Path) -> None:
    """고정 리비전의 Hugging Face 스냅샷과 출처 표식을 설치한다."""
    source = tmp_path / "hf-source"
    source.mkdir()
    (source / "config.json").write_text('{"model_type":"test"}', encoding="utf-8")
    (source / "model.safetensors").write_bytes(b"hf-weights")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_hf = fake_bin / "hf"
    fake_hf.write_text(
        """#!/usr/bin/env bash
set -eu
target=
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--local-dir" ]]; then
    target="$2"
    shift 2
  else
    shift
  fi
done
mkdir -p "$target"
cp -a "$FAKE_HF_SOURCE/." "$target/"
""",
        encoding="utf-8",
    )
    fake_hf.chmod(0o755)
    revision = "5" * 40

    result = _run_prepare(
        tmp_path,
        None,
        "",
        env_overrides={
            "MODEL_HF_REPO_ID": "owner/model",
            "MODEL_HF_REVISION": revision,
            "FAKE_HF_SOURCE": str(source),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    model_path = tmp_path / "data" / "models" / "gemma4"
    assert result.returncode == 0, result.stderr
    assert (model_path / "model.safetensors").read_bytes() == b"hf-weights"
    assert (
        model_path / ".mininblm-model.source"
    ).read_text().strip() == f"hf:owner/model@{revision}"
    assert not list((tmp_path / "data" / "model-cache").glob("*.part"))