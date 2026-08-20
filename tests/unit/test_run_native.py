import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "run-native.sh"


def test_prepare_postgres_storage_uses_mapped_volume_owner(tmp_path: Path) -> None:
    """매핑 볼륨의 소유권 변경이 막히면 실제 소유 사용자로 전환한다."""
    data_dir = tmp_path / "postgres"
    socket_dir = tmp_path / "socket"
    log_dir = tmp_path / "logs"
    fake_bin = tmp_path / "bin"
    data_dir.mkdir()
    socket_dir.mkdir()
    log_dir.mkdir()
    (log_dir / "db.log").touch()
    fake_bin.mkdir()

    fake_id = fake_bin / "id"
    fake_id.write_text(
        """#!/usr/bin/env bash
if [[ "$#" -eq 1 && "$1" == "-u" ]]; then
  echo 0
  exit 0
fi
exec /usr/bin/id "$@"
""",
        encoding="utf-8",
    )
    fake_id.chmod(0o755)

    fake_chown = fake_bin / "chown"
    fake_chown.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_chown.chmod(0o755)

    fake_stat = fake_bin / "stat"
    fake_stat.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "-c" && "$2" == "%u" ]]; then
  echo 65534
  exit 0
fi
if [[ "$1" == "-c" && "$2" == "%g" ]]; then
  echo 65534
  exit 0
fi
exec /usr/bin/stat "$@"
""",
        encoding="utf-8",
    )
    fake_stat.chmod(0o755)

    command = f"""
source {SCRIPT}
POSTGRES_DATA_DIR={data_dir}
POSTGRES_SOCKET_DIR={socket_dir}
LOG_DIR={log_dir}
DB_OS_USER=root
prepare_postgres_storage
printf 'selected=%s\\n' "$DB_OS_USER"
"""
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "소유권 변경이 제한된 storage를 감지했습니다" in result.stdout
    assert "selected=nobody" in result.stdout
