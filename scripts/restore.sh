#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(docker compose --profile llm)
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
  ./restore.sh --verify-only <backup.tar.gz>
  ./restore.sh --yes <backup.tar.gz>

--verify-only validates the archive without changing data.
--yes replaces the current database and uploaded PDFs.
EOF
}

mode="${1:-}"
archive="${2:-}"
if [[ "$mode" == "--help" || "$mode" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "$mode" != "--verify-only" && "$mode" != "--yes" ]] || [[ -z "$archive" ]] || [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi
archive="$(realpath "$archive")"
[[ -f "$archive" ]] || {
  echo "오류: 백업 파일을 찾을 수 없습니다: $archive" >&2
  exit 1
}
[[ -n "$UPLOADS_DIR" && "$UPLOADS_DIR" != "/" ]] || {
  echo "오류: 안전하지 않은 UPLOADS_DIR입니다." >&2
  exit 1
}

for command in docker tar sha256sum mktemp realpath; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "오류: '$command' 명령을 찾을 수 없습니다." >&2
    exit 1
  }
done

staging_dir="$(mktemp -d "${TMPDIR:-/tmp}/mininblm-restore.XXXXXX")"
rollback_dir="$staging_dir/rollback"
staged_data_dir="$staging_dir/staged-data"
mkdir -p "$rollback_dir" "$staged_data_dir"
api_was_stopped=false
restore_started=false
restore_succeeded=false

replace_uploads() {
  local uploads_archive="$1"
  "${COMPOSE[@]}" run --rm --no-deps -T \
    -v "$uploads_archive:/restore/uploads.tar.gz:ro" \
    --entrypoint sh api -c \
    'set -eu; rm -rf /app/data/uploads; mkdir -p /app/data; tar --no-same-owner --no-same-permissions -xzf /restore/uploads.tar.gz -C /app/data'
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ "$restore_started" == true && "$restore_succeeded" != true ]]; then
    echo "복원에 실패하여 기존 데이터로 rollback합니다." >&2
    "${COMPOSE[@]}" exec -T "$DB_SERVICE" \
      pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error \
      --host 127.0.0.1 --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_NAME" \
      <"$rollback_dir/database.dump" || true
    replace_uploads "$rollback_dir/uploads.tar.gz" || true
  fi
  if [[ "$api_was_stopped" == true ]]; then
    echo "API 서비스를 다시 시작합니다."
    "${COMPOSE[@]}" start api >/dev/null || true
  fi
  rm -rf -- "$staging_dir"
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

unexpected_entry="$(
  tar -tzf "$archive" | sed 's#^\./##' \
    | grep -Ev '^(database\.dump|uploads\.tar\.gz|manifest\.txt|SHA256SUMS)$' \
    | head -n 1 || true
)"
if [[ -n "$unexpected_entry" ]]; then
  echo "오류: 허용되지 않은 백업 항목입니다: $unexpected_entry" >&2
  exit 1
fi
tar -xzf "$archive" -C "$staging_dir" \
  database.dump uploads.tar.gz manifest.txt SHA256SUMS
[[ "$(wc -l <"$staging_dir/SHA256SUMS")" -eq 3 ]] || {
  echo "오류: checksum 항목 수가 올바르지 않습니다." >&2
  exit 1
}
for item in database.dump uploads.tar.gz manifest.txt; do
  expected_checksum="$(awk -v file="$item" '$2 == file {print $1}' "$staging_dir/SHA256SUMS")"
  [[ "$expected_checksum" =~ ^[0-9a-f]{64}$ ]] || {
    echo "오류: $item checksum 항목이 올바르지 않습니다." >&2
    exit 1
  }
  actual_checksum="$(sha256sum "$staging_dir/$item" | awk '{print $1}')"
  [[ "$actual_checksum" == "$expected_checksum" ]] || {
    echo "오류: $item checksum이 일치하지 않습니다." >&2
    exit 1
  }
  echo "$item: OK"
done
grep -qx 'format_version=1' "$staging_dir/manifest.txt" || {
  echo "오류: 지원하지 않는 백업 형식입니다." >&2
  exit 1
}

unsafe_upload_entry="$(
  tar -tzf "$staging_dir/uploads.tar.gz" \
    | grep -E '(^/|(^|/)\.\.(/|$))' \
    | head -n 1 || true
)"
if [[ -n "$unsafe_upload_entry" ]]; then
  echo "오류: 안전하지 않은 업로드 경로입니다: $unsafe_upload_entry" >&2
  exit 1
fi
uploads_name="$(basename "$UPLOADS_DIR")"
unexpected_upload_entry="$(
  while IFS= read -r entry; do
    entry="${entry#./}"
    case "$entry" in
      "$uploads_name"|"$uploads_name/"*) ;;
      *) printf '%s\n' "$entry"; break ;;
    esac
  done < <(tar -tzf "$staging_dir/uploads.tar.gz")
)"
if [[ -n "$unexpected_upload_entry" ]]; then
  echo "오류: uploads 밖의 백업 경로입니다: $unexpected_upload_entry" >&2
  exit 1
fi
link_upload_entry="$(tar -tvzf "$staging_dir/uploads.tar.gz" | awk '$1 ~ /^[lh]/ {print $NF; exit}')"
if [[ -n "$link_upload_entry" ]]; then
  echo "오류: uploads 백업에 link가 포함되어 있습니다: $link_upload_entry" >&2
  exit 1
fi
tar --no-same-owner --no-same-permissions -xzf "$staging_dir/uploads.tar.gz" -C "$staged_data_dir"
[[ -d "$staged_data_dir/$uploads_name" ]] || {
  echo "오류: 백업에 uploads 디렉터리가 없습니다." >&2
  exit 1
}

echo "백업 검증 완료: $archive"
if [[ "$mode" == "--verify-only" ]]; then
  trap - EXIT INT TERM
  rm -rf -- "$staging_dir"
  exit 0
fi

"${COMPOSE[@]}" ps --status running "$DB_SERVICE" | grep -q "$DB_SERVICE" || {
  echo "오류: DB 컨테이너가 실행 중이 아닙니다." >&2
  exit 1
}

api_container="$("${COMPOSE[@]}" ps -q api)"
if [[ -n "$api_container" && "$(docker inspect --format '{{.State.Running}}' "$api_container")" == "true" ]]; then
  echo "복원을 위해 API 서비스를 정지합니다."
  "${COMPOSE[@]}" stop api >/dev/null
  api_was_stopped=true
fi

echo "복원 전 rollback snapshot을 생성합니다."
"${COMPOSE[@]}" exec -T "$DB_SERVICE" \
  pg_dump --format=custom --no-owner --no-privileges \
  --host 127.0.0.1 --port "$DB_PORT" --username "$DB_USER" "$DB_NAME" \
  >"$rollback_dir/database.dump"
if [[ -d "$UPLOADS_DIR" ]]; then
  tar -czf "$rollback_dir/uploads.tar.gz" \
    -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")"
else
  mkdir -p "$rollback_dir/empty-data/$(basename "$UPLOADS_DIR")"
  tar -czf "$rollback_dir/uploads.tar.gz" \
    -C "$rollback_dir/empty-data" "$(basename "$UPLOADS_DIR")"
fi
restore_started=true

echo "PostgreSQL을 복원합니다."
"${COMPOSE[@]}" exec -T "$DB_SERVICE" \
  pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error \
  --host 127.0.0.1 --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_NAME" \
  <"$staging_dir/database.dump"

replace_uploads "$staging_dir/uploads.tar.gz"
restore_succeeded=true

if [[ "$api_was_stopped" == true ]]; then
  echo "API 서비스를 다시 시작합니다."
  "${COMPOSE[@]}" start api >/dev/null
  api_was_stopped=false
fi

trap - EXIT INT TERM
rm -rf -- "$staging_dir"
echo "복원 완료: $archive"
