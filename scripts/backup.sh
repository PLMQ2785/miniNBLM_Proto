#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(docker compose --profile llm)
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
UPLOADS_DIR="${UPLOADS_DIR:-$PROJECT_DIR/data/uploads}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_NAME="${DB_NAME:-rag_db}"
DB_USER="${DB_USER:-rag_user}"
DB_PORT="${DB_PORT:-}"
if [[ -z "$DB_PORT" && -f .env ]]; then
  DB_PORT="$(sed -n 's/^MININBLM_DB_PORT=//p' .env | tail -n 1)"
fi
DB_PORT="${DB_PORT:-5433}"

usage() {
  cat <<'EOF'
Usage:
  ./backup.sh

Environment:
  BACKUP_DIR   Backup destination (default: ./backups)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

for command in docker tar sha256sum mktemp; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "오류: '$command' 명령을 찾을 수 없습니다." >&2
    exit 1
  }
done
"${COMPOSE[@]}" ps --status running "$DB_SERVICE" | grep -q "$DB_SERVICE" || {
  echo "오류: DB 컨테이너가 실행 중이 아닙니다." >&2
  exit 1
}

mkdir -p "$BACKUP_DIR"
staging_dir="$(mktemp -d "$BACKUP_DIR/.backup-staging.XXXXXX")"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$BACKUP_DIR/mininblm-backup-$timestamp.tar.gz"
temporary_archive="$archive.tmp"
api_was_stopped=false

cleanup() {
  local exit_code=$?
  rm -rf -- "$staging_dir" "$temporary_archive"
  if [[ "$api_was_stopped" == true ]]; then
    echo "API 서비스를 다시 시작합니다."
    "${COMPOSE[@]}" start api >/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

api_container="$("${COMPOSE[@]}" ps -q api)"
if [[ -n "$api_container" && "$(docker inspect --format '{{.State.Running}}' "$api_container")" == "true" ]]; then
  echo "일관된 백업을 위해 API 서비스를 잠시 정지합니다."
  "${COMPOSE[@]}" stop api >/dev/null
  api_was_stopped=true
fi

echo "PostgreSQL을 백업합니다."
"${COMPOSE[@]}" exec -T "$DB_SERVICE" \
  pg_dump --format=custom --no-owner --no-privileges \
  --host 127.0.0.1 --port "$DB_PORT" --username "$DB_USER" "$DB_NAME" \
  >"$staging_dir/database.dump"

echo "업로드 PDF를 백업합니다."
if [[ -d "$UPLOADS_DIR" ]]; then
  if find "$UPLOADS_DIR" -type l -print -quit | grep -q .; then
    echo "오류: uploads에 symbolic link가 있어 안전하게 백업할 수 없습니다." >&2
    exit 1
  fi
  tar -czf "$staging_dir/uploads.tar.gz" -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")"
else
  mkdir -p "$staging_dir/empty-data/$(basename "$UPLOADS_DIR")"
  tar -czf "$staging_dir/uploads.tar.gz" -C "$staging_dir/empty-data" "$(basename "$UPLOADS_DIR")"
fi

git_commit="$(git rev-parse --verify HEAD 2>/dev/null || printf 'unknown')"
cat >"$staging_dir/manifest.txt" <<EOF
format_version=1
created_at_utc=$timestamp
git_commit=$git_commit
database=$DB_NAME
uploads_directory=$(basename "$UPLOADS_DIR")
EOF

(
  cd "$staging_dir"
  sha256sum database.dump uploads.tar.gz manifest.txt >SHA256SUMS
)
tar -czf "$temporary_archive" -C "$staging_dir" \
  database.dump uploads.tar.gz manifest.txt SHA256SUMS
mv -- "$temporary_archive" "$archive"
chmod 600 "$archive"

if [[ "$api_was_stopped" == true ]]; then
  echo "API 서비스를 다시 시작합니다."
  "${COMPOSE[@]}" start api >/dev/null
  api_was_stopped=false
fi

trap - EXIT INT TERM
rm -rf -- "$staging_dir"
echo "백업 완료: $archive"
