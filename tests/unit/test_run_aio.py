import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "run_aio.sh"


def test_launcher_accepts_current_hf_model_settings(tmp_path: Path) -> None:
    """현재 MODEL_HF 설정이 폐기된 변수 없이 기동 검증을 통과한다."""
    env_file = tmp_path / ".env.all-in-one"
    env_file.write_text(
        "\n".join(
            [
                "NATIVE_DB_PASSWORD=Test-Database-2026!",
                "MODEL_HF_REPO_ID=owner/model",
                f"MODEL_HF_REVISION={'a' * 40}",
            ]
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "AIO_ENV_FILE": str(env_file),
            "BOOTSTRAP_ADMIN_PASSWORD": "",
            "BOOTSTRAP_ADMIN_USERNAME": "",
            "MODEL_REPOSITORY": "",
            "MININBLM_MODEL_VOLUME": "",
            "NATIVE_DB_PASSWORD": "Test-Database-2026!",
            "PATH": f"{fake_bin}:{env['PATH']}",
            "STARTUP_TIMEOUT": "1",
        }
    )

    result = subprocess.run(
        [str(SCRIPT), "--no-build"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "원샷 통합 컨테이너가 준비되었습니다." in result.stdout
