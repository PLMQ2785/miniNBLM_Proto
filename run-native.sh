#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./run-native.sh setup          Install API and embedding dependencies
  ./run-native.sh setup-llm      Install and patch the local vLLM runtime
  ./run-native.sh doctor         Check native runtime prerequisites
  ./run-native.sh up             Start services in the background
  ./run-native.sh start-api      Start only the native API process
  ./run-native.sh stop-api       Stop only the native API process
  ./run-native.sh foreground     Start services and remain in the foreground
  ./run-native.sh down           Stop locally managed services
  ./run-native.sh status         Show locally managed service status
  ./run-native.sh logs [service] Follow logs (api, embedding, llm, db)

The native runtime never invokes Docker. Set NATIVE_MANAGE_DB,
NATIVE_START_EMBEDDING, or NATIVE_START_LLM=false to use external services.
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "오류: '$1' 명령을 찾을 수 없습니다." >&2
    return 1
  fi
}

env_value() {
  local key="$1"
  local default_value="${2:-}"
  local name value
  if [[ -f "$PROJECT_DIR/.env" ]]; then
    while IFS='=' read -r name value; do
      [[ "$name" == "$key" ]] || continue
      value="${value%$'\r'}"
      if [[ "$value" == \"*\" && "$value" == *\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
        value="${value:1:${#value}-2}"
      fi
      printf '%s' "$value"
      return
    done <"$PROJECT_DIR/.env"
  fi
  printf '%s' "$default_value"
}

absolute_path() {
  local value="$1"
  if [[ "$value" == /* ]]; then
    printf '%s' "$value"
  else
    printf '%s/%s' "$PROJECT_DIR" "${value#./}"
  fi
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

ensure_env_file() {
  if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo ".env.example을 복사해 .env를 생성했습니다."
  fi
}

urlencode() {
  python3 -c 'import sys; from urllib.parse import quote; print(quote(sys.argv[1], safe=""))' "$1"
}
redact_database_url() {
  printf '%s' "$1" | sed -E 's#(://[^:/@]+:)[^@]+@#\1***@#'
}


load_config() {
  DB_PORT="${MININBLM_DB_PORT:-$(env_value MININBLM_DB_PORT 5433)}"
  DB_NAME="${NATIVE_DB_NAME:-$(env_value NATIVE_DB_NAME rag_db)}"
  DB_USER="${NATIVE_DB_USER:-$(env_value NATIVE_DB_USER rag_user)}"
  DB_PASSWORD="${NATIVE_DB_PASSWORD:-$(env_value NATIVE_DB_PASSWORD rag_password)}"
  DB_OS_USER="${NATIVE_DB_OS_USER:-$(env_value NATIVE_DB_OS_USER postgres)}"
  MANAGE_DB="${NATIVE_MANAGE_DB:-$(env_value NATIVE_MANAGE_DB true)}"
  START_EMBEDDING="${NATIVE_START_EMBEDDING:-$(env_value NATIVE_START_EMBEDDING true)}"
  START_LLM="${NATIVE_START_LLM:-$(env_value NATIVE_START_LLM true)}"

  API_HOST="${NATIVE_API_HOST:-$(env_value NATIVE_API_HOST 0.0.0.0)}"
  API_PORT="${NATIVE_API_PORT:-$(env_value NATIVE_API_PORT 8080)}"
  EMBEDDING_PORT="${NATIVE_EMBEDDING_PORT:-$(env_value NATIVE_EMBEDDING_PORT 8070)}"
  LLM_PORT="${NATIVE_LLM_PORT:-$(env_value NATIVE_LLM_PORT 8010)}"
  STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-$(env_value STARTUP_TIMEOUT 900)}"

  NATIVE_ENV_DIR="$(absolute_path "${NATIVE_ENV_DIR:-$(env_value NATIVE_ENV_DIR .venv-native)}")"
  VLLM_ENV_DIR="$(absolute_path "${NATIVE_VLLM_ENV_DIR:-$(env_value NATIVE_VLLM_ENV_DIR .venv-vllm)}")"
  POSTGRES_DATA_DIR="$(absolute_path "${NATIVE_DB_DATA_DIR:-$(env_value NATIVE_DB_DATA_DIR .native/postgres)}")"
  RUNTIME_DIR="$(absolute_path "${NATIVE_RUNTIME_DIR:-$(env_value NATIVE_RUNTIME_DIR .native/run)}")"
  LOG_DIR="$(absolute_path "${NATIVE_LOG_DIR:-$(env_value NATIVE_LOG_DIR .native/logs)}")"
  HF_HOME_DIR="$(absolute_path "${HF_HOME:-$(env_value HF_HOME .native/huggingface)}")"
  UPLOAD_DIR_VALUE="$(absolute_path "${NATIVE_UPLOAD_DIR:-$(env_value NATIVE_UPLOAD_DIR .native/uploads)}")"

  MODEL_PATH="$(absolute_path "${VLLM_MODEL_PATH:-$(env_value VLLM_MODEL_PATH google/gemma-4-12B-it-W4A16)}")"
  VLLM_MODEL_NAME="${VLLM_MODEL_NAME:-$(env_value VLLM_MODEL_NAME gemma4)}"
  VLLM_MAX_MODEL_LEN_VALUE="${VLLM_MAX_MODEL_LEN:-$(env_value VLLM_MAX_MODEL_LEN 16384)}"
  VLLM_GPU_MEMORY_VALUE="${VLLM_GPU_MEMORY_UTILIZATION:-$(env_value VLLM_GPU_MEMORY_UTILIZATION 0.65)}"
  VLLM_MAX_NUM_SEQS_VALUE="${VLLM_MAX_NUM_SEQS:-$(env_value VLLM_MAX_NUM_SEQS 4)}"
  VLLM_CPU_OFFLOAD_GB_VALUE="${VLLM_CPU_OFFLOAD_GB:-$(env_value VLLM_CPU_OFFLOAD_GB 0)}"
  VLLM_TENSOR_PARALLEL_SIZE_VALUE="${VLLM_TENSOR_PARALLEL_SIZE:-$(env_value VLLM_TENSOR_PARALLEL_SIZE 1)}"
  VLLM_VERSION="${NATIVE_VLLM_VERSION:-$(env_value NATIVE_VLLM_VERSION 0.25.0)}"

  if is_true "$MANAGE_DB"; then
    local encoded_password
    encoded_password="$(urlencode "$DB_PASSWORD")"
    DATABASE_URL_VALUE="postgresql+psycopg://$DB_USER:$encoded_password@127.0.0.1:$DB_PORT/$DB_NAME"
  else
    DATABASE_URL_VALUE="${DATABASE_URL:-$(env_value DATABASE_URL "postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:$DB_PORT/$DB_NAME")}"
  fi
  EMBEDDING_BASE_URL_VALUE="${EMBEDDING_BASE_URL:-$(env_value EMBEDDING_BASE_URL "http://127.0.0.1:$EMBEDDING_PORT")}"
  LLM_HEALTH_URL="${NATIVE_LLM_HEALTH_URL:-$(env_value NATIVE_LLM_HEALTH_URL "http://127.0.0.1:$LLM_PORT/v1/models")}"
  LLM_ENDPOINTS_FILE_VALUE="$(absolute_path "${LLM_ENDPOINTS_FILE:-$(env_value LLM_ENDPOINTS_FILE config/llm-endpoints.json)}")"
  [[ -f "$LLM_ENDPOINTS_FILE_VALUE" ]] || {
    echo "오류: 언어모델 설정 파일을 찾을 수 없습니다: $LLM_ENDPOINTS_FILE_VALUE" >&2
    return 1
  }

  NATIVE_PYTHON="$NATIVE_ENV_DIR/bin/python"
  VLLM_PYTHON="$VLLM_ENV_DIR/bin/python"
  VLLM_BIN="${NATIVE_VLLM_BIN:-$VLLM_ENV_DIR/bin/vllm}"
  POSTGRES_SOCKET_DIR="$RUNTIME_DIR/postgres-socket"

  mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$HF_HOME_DIR" "$UPLOAD_DIR_VALUE"
}

pid_file() {
  printf '%s/%s.pid' "$RUNTIME_DIR" "$1"
}

log_file() {
  printf '%s/%s.log' "$LOG_DIR" "$1"
}
maintenance_file() {
  printf '%s/api.maintenance' "$RUNTIME_DIR"
}


service_pid() {
  local file
  file="$(pid_file "$1")"
  [[ -f "$file" ]] || return 1
  tr -d '[:space:]' <"$file"
}

service_running() {
  local pid
  pid="$(service_pid "$1" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

start_process() {
  local service="$1"
  shift
  if service_running "$service"; then
    echo "$service: 이미 실행 중입니다 (PID $(service_pid "$service"))."
    return
  fi
  rm -f "$(pid_file "$service")"
  echo "$service 서비스를 시작합니다. 로그: $(log_file "$service")"
  nohup "$@" >>"$(log_file "$service")" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "$pid" >"$(pid_file "$service")"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "오류: $service 시작에 실패했습니다." >&2
    tail -n 80 "$(log_file "$service")" >&2 || true
    return 1
  fi
}

stop_process() {
  local service="$1"
  local pid
  pid="$(service_pid "$service" 2>/dev/null || true)"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$(pid_file "$service")"
    echo "$service: 중지 상태"
    return
  fi
  echo "$service 서비스를 종료합니다 (PID $pid)."
  kill "$pid" 2>/dev/null || true
  local deadline=$((SECONDS + 30))
  while kill -0 "$pid" 2>/dev/null && (( SECONDS < deadline )); do
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "오류: $service 프로세스가 30초 안에 종료되지 않았습니다 (PID $pid)." >&2
    return 1
  fi
  rm -f "$(pid_file "$service")"
}

wait_for_http() {
  local service="$1"
  local url="$2"
  local deadline=$((SECONDS + STARTUP_TIMEOUT))
  printf '%s 준비 대기 중' "$service"
  until curl -fsS --max-time 5 "$url" >/dev/null 2>&1; do
    if [[ "$service" != "external" ]] && [[ -f "$(pid_file "$service")" ]] && ! service_running "$service"; then
      echo
      echo "오류: $service 프로세스가 준비 전에 종료되었습니다." >&2
      tail -n 80 "$(log_file "$service")" >&2 || true
      return 1
    fi
    if (( SECONDS >= deadline )); then
      echo
      echo "오류: $service 준비 시간이 ${STARTUP_TIMEOUT}초를 초과했습니다: $url" >&2
      [[ "$service" == "external" ]] || tail -n 80 "$(log_file "$service")" >&2 || true
      return 1
    fi
    printf '.'
    sleep 3
  done
  echo " 완료"
}

resolve_postgres_bin() {
  if [[ -n "${POSTGRES_BIN_DIR:-}" ]]; then
    printf '%s' "$POSTGRES_BIN_DIR"
    return
  fi
  if command -v pg_config >/dev/null 2>&1; then
    local configured_bin
    configured_bin="$(pg_config --bindir)"
    if [[ -x "$configured_bin/postgres" ]]; then
      printf '%s' "$configured_bin"
      return
    fi
  fi
  local candidate selected=""
  for candidate in /usr/lib/postgresql/*/bin; do
    [[ -x "$candidate/postgres" ]] && selected="$candidate"
  done
  [[ -n "$selected" ]] || return 1
  printf '%s' "$selected"
}
postgres_as_owner() {
  if [[ "$(id -u)" -eq 0 ]]; then
    runuser -u "$DB_OS_USER" -- "$@"
  else
    "$@"
  fi
}


postgres_with_password() {
  if [[ "$(id -u)" -eq 0 ]]; then
    runuser -u "$DB_OS_USER" -- env PGPASSWORD="$DB_PASSWORD" "$@"
  else
    env PGPASSWORD="$DB_PASSWORD" "$@"
  fi
}


prepare_postgres_storage() {
  local data_uid desired_uid selected_uid selected_group owner_record

  mkdir -p "$POSTGRES_DATA_DIR" "$POSTGRES_SOCKET_DIR"
  touch "$(log_file db)"
  chmod 700 "$POSTGRES_DATA_DIR" "$POSTGRES_SOCKET_DIR"
  [[ "$(id -u)" -eq 0 ]] || return 0

  desired_uid="$(id -u "$DB_OS_USER")"
  data_uid="$(stat -c '%u' "$POSTGRES_DATA_DIR")"
  if [[ "$data_uid" != "$desired_uid" ]] \
      && ! chown -R "$DB_OS_USER:$(id -gn "$DB_OS_USER")" "$POSTGRES_DATA_DIR" 2>/dev/null; then
    data_uid="$(stat -c '%u' "$POSTGRES_DATA_DIR")"
    [[ "$data_uid" != "0" ]] || {
      echo "오류: PostgreSQL data 경로의 chown이 차단되었고 소유자가 root입니다: $POSTGRES_DATA_DIR" >&2
      echo "NATIVE_DB_DATA_DIR을 소유권 변경이 가능한 local disk 경로로 설정하십시오." >&2
      return 1
    }
    owner_record="$(getent passwd "$data_uid" || true)"
    [[ -n "$owner_record" ]] || {
      echo "오류: PostgreSQL data 경로 UID $data_uid에 대응하는 container 사용자가 없습니다." >&2
      return 1
    }
    DB_OS_USER="${owner_record%%:*}"
    echo "소유권 변경이 제한된 storage를 감지했습니다. PostgreSQL을 UID $data_uid ($DB_OS_USER)로 실행합니다."
  fi

  selected_uid="$(id -u "$DB_OS_USER")"
  selected_group="$(id -gn "$DB_OS_USER")"
  if [[ "$(stat -c '%u' "$POSTGRES_SOCKET_DIR")" != "$selected_uid" ]]; then
    chown "$DB_OS_USER:$selected_group" "$POSTGRES_SOCKET_DIR"
  fi
  if [[ "$(stat -c '%u' "$(log_file db)")" != "$selected_uid" ]] \
      && ! chown "$DB_OS_USER:$selected_group" "$(log_file db)" 2>/dev/null; then
    echo "오류: PostgreSQL 로그 파일을 UID $selected_uid가 쓸 수 없습니다: $(log_file db)" >&2
    return 1
  fi
}



start_database() {
  is_true "$MANAGE_DB" || return 0
  [[ "$DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "오류: NATIVE_DB_NAME이 안전한 PostgreSQL 식별자가 아닙니다." >&2
    return 1
  }
  [[ "$DB_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "오류: NATIVE_DB_USER가 안전한 PostgreSQL 식별자가 아닙니다." >&2
    return 1
  }
  local pg_bin
  pg_bin="$(resolve_postgres_bin)" || {
    echo "오류: PostgreSQL 실행 파일을 찾을 수 없습니다. POSTGRES_BIN_DIR를 설정하십시오." >&2
    return 1
  }
  for command in initdb pg_ctl pg_isready createdb psql; do
    [[ -x "$pg_bin/$command" ]] || {
      echo "오류: PostgreSQL 명령이 없습니다: $pg_bin/$command" >&2
      return 1
    }
  done
  if [[ "$(id -u)" -eq 0 ]]; then
    require_command runuser
    id "$DB_OS_USER" >/dev/null 2>&1 || {
      echo "오류: PostgreSQL OS 사용자가 없습니다: $DB_OS_USER" >&2
      return 1
    }
  fi

  prepare_postgres_storage
  if [[ ! -f "$POSTGRES_DATA_DIR/PG_VERSION" ]]; then
    if "$pg_bin/pg_isready" -h 127.0.0.1 -p "$DB_PORT" >/dev/null 2>&1; then
      echo "오류: $DB_PORT 포트를 다른 PostgreSQL이 사용 중입니다." >&2
      return 1
    fi
    local password_file="$RUNTIME_DIR/postgres-password"
    umask 077
    printf '%s\n' "$DB_PASSWORD" >"$password_file"
    if [[ "$(id -u)" -eq 0 \
        && "$(stat -c '%u' "$password_file")" != "$(id -u "$DB_OS_USER")" ]]; then
      chown "$DB_OS_USER:$(id -gn "$DB_OS_USER")" "$password_file"
    fi
    if ! postgres_as_owner "$pg_bin/initdb" \
      --pgdata "$POSTGRES_DATA_DIR" \
      --username "$DB_USER" \
      --pwfile "$password_file" \
      --auth-host scram-sha-256 \
      --auth-local trust \
      --encoding UTF8 \
      --no-locale >>"$(log_file db)" 2>&1; then
      rm -f "$password_file"
      return 1
    fi
    rm -f "$password_file"
  fi

  if ! postgres_as_owner "$pg_bin/pg_ctl" status -D "$POSTGRES_DATA_DIR" >/dev/null 2>&1; then
    postgres_as_owner "$pg_bin/pg_ctl" -D "$POSTGRES_DATA_DIR" \
      -l "$(log_file db)" \
      -o "-h 127.0.0.1 -p $DB_PORT -k $POSTGRES_SOCKET_DIR" \
      -w start
  fi
  local postgres_pid
  postgres_pid="$(sed -n '1p' "$POSTGRES_DATA_DIR/postmaster.pid")"
  printf '%s\n' "$postgres_pid" >"$(pid_file db)"

  local database_exists
  database_exists="$(
    postgres_with_password "$pg_bin/psql" \
      -h 127.0.0.1 -p "$DB_PORT" -U "$DB_USER" -d postgres \
      -Atqc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'"
  )"
  if [[ "$database_exists" != "1" ]]; then
    postgres_with_password "$pg_bin/createdb" \
      -h 127.0.0.1 -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"
  fi
  echo "db: 준비 완료 (PID $postgres_pid)"
}


stop_database() {
  is_true "$MANAGE_DB" || return 0
  local pg_bin
  pg_bin="$(resolve_postgres_bin 2>/dev/null || true)"
  if [[ -n "$pg_bin" && -f "$POSTGRES_DATA_DIR/PG_VERSION" ]] \
      && postgres_as_owner "$pg_bin/pg_ctl" status -D "$POSTGRES_DATA_DIR" >/dev/null 2>&1; then
    echo "db 서비스를 종료합니다."
    postgres_as_owner "$pg_bin/pg_ctl" -D "$POSTGRES_DATA_DIR" -m fast -w stop
  fi
  rm -f "$(pid_file db)"
}

run_migrations() {
  echo "Alembic migration을 적용합니다."
  env DATABASE_URL="$DATABASE_URL_VALUE" UPLOAD_DIR="$UPLOAD_DIR_VALUE" \
    LLM_ENDPOINTS_FILE="$LLM_ENDPOINTS_FILE_VALUE" \
    "$NATIVE_PYTHON" -m alembic upgrade head
}

start_embedding() {
  is_true "$START_EMBEDDING" || return 0
  start_process embedding \
    env HF_HOME="$HF_HOME_DIR" \
    "$NATIVE_PYTHON" -m uvicorn embedding_service.main:app \
    --host 127.0.0.1 --port "$EMBEDDING_PORT" --no-access-log
}

start_llm() {
  is_true "$START_LLM" || return 0
  [[ -x "$VLLM_BIN" ]] || {
    echo "오류: vLLM 실행 파일이 없습니다: $VLLM_BIN" >&2
    echo "먼저 ./run-native.sh setup-llm을 실행하십시오." >&2
    return 1
  }
  [[ -f "$MODEL_PATH/config.json" ]] || {
    echo "오류: 모델 config.json을 찾을 수 없습니다: $MODEL_PATH" >&2
    return 1
  }
  start_process llm \
    env HF_HOME="$HF_HOME_DIR" VLLM_WSL2_ENABLE_PIN_MEMORY="${VLLM_WSL2_ENABLE_PIN_MEMORY:-1}" \
    "$VLLM_BIN" serve "$MODEL_PATH" \
    --served-model-name "$VLLM_MODEL_NAME" \
    --dtype bfloat16 \
    --max-model-len "$VLLM_MAX_MODEL_LEN_VALUE" \
    --gpu-memory-utilization "$VLLM_GPU_MEMORY_VALUE" \
    --max-num-seqs "$VLLM_MAX_NUM_SEQS_VALUE" \
    --cpu-offload-gb "$VLLM_CPU_OFFLOAD_GB_VALUE" \
    --tensor-parallel-size "$VLLM_TENSOR_PARALLEL_SIZE_VALUE" \
    --limit-mm-per-prompt.image 1 \
    --host 127.0.0.1 --port "$LLM_PORT"
}

validate_api_config() {
  echo "API 설정을 검증합니다."
  if ! env LLM_ENDPOINTS_FILE="$LLM_ENDPOINTS_FILE_VALUE" \
      "$NATIVE_PYTHON" -c 'from app.config import settings' ; then
    echo "오류: API 설정이 유효하지 않습니다: $LLM_ENDPOINTS_FILE_VALUE" >&2
    return 1
  fi
}


start_api() {
  run_migrations
  start_process api \
    env DATABASE_URL="$DATABASE_URL_VALUE" UPLOAD_DIR="$UPLOAD_DIR_VALUE" \
    EMBEDDING_BASE_URL="$EMBEDDING_BASE_URL_VALUE" \
    LLM_ENDPOINTS_FILE="$LLM_ENDPOINTS_FILE_VALUE" \
    "$NATIVE_PYTHON" -m uvicorn app.main:app \
    --host "$API_HOST" --port "$API_PORT" --no-access-log
}

start_all() {
  require_command curl
  [[ -x "$NATIVE_PYTHON" ]] || {
    echo "오류: native Python 환경이 없습니다: $NATIVE_PYTHON" >&2
    echo "먼저 ./run-native.sh setup을 실행하십시오." >&2
    return 1
  }
  validate_api_config

  start_database
  start_embedding
  start_llm

  if is_true "$START_EMBEDDING"; then
    wait_for_http embedding "http://127.0.0.1:$EMBEDDING_PORT/health"
  else
    wait_for_http external "${EMBEDDING_BASE_URL_VALUE%/}/health"
  fi
  if is_true "$START_LLM"; then
    wait_for_http llm "http://127.0.0.1:$LLM_PORT/v1/models"
  else
    wait_for_http external "$LLM_HEALTH_URL"
  fi

  rm -f "$(maintenance_file)"
  start_api
  wait_for_http api "http://127.0.0.1:$API_PORT/health/ready"
  echo
  echo "비컨테이너 서비스가 준비되었습니다: http://localhost:$API_PORT/"
}

stop_all() {
  local failed=false
  stop_process api || failed=true
  is_true "$START_LLM" && stop_process llm || true
  is_true "$START_EMBEDDING" && stop_process embedding || true
  stop_database || failed=true
  rm -f "$(maintenance_file)"
  [[ "$failed" == false ]]
}

print_status() {
  local service
  for service in api embedding llm db; do
    case "$service" in
      embedding) is_true "$START_EMBEDDING" || { printf '%-10s external (%s)\n' "$service" "$EMBEDDING_BASE_URL_VALUE"; continue; } ;;
      llm) is_true "$START_LLM" || { printf '%-10s external (%s)\n' "$service" "$LLM_HEALTH_URL"; continue; } ;;
      db) is_true "$MANAGE_DB" || { printf '%-10s external (%s)\n' "$service" "$(redact_database_url "$DATABASE_URL_VALUE")"; continue; } ;;
    esac
    if service_running "$service"; then
      printf '%-10s running (PID %s)\n' "$service" "$(service_pid "$service")"
    else
      printf '%-10s stopped\n' "$service"
    fi
  done
}

setup_native() {
  require_command uv
  echo "API와 embedding 의존성을 $NATIVE_ENV_DIR 에 설치합니다."
  UV_PROJECT_ENVIRONMENT="$NATIVE_ENV_DIR" \
    uv sync --frozen --only-group api --only-group embedding
  echo "설치 완료. PostgreSQL/pgvector와 vLLM은 ./run-native.sh doctor로 확인하십시오."
}

vllm_source_path() {
  "$VLLM_PYTHON" - <<'PY'
from pathlib import Path
import vllm

print(Path(vllm.__file__).resolve().parent / "model_executor" / "models" / "gemma4_unified.py")
PY
}

setup_vllm() {
  require_command uv
  require_command patch
  if [[ ! -x "$VLLM_PYTHON" ]]; then
    uv venv --python 3.12 "$VLLM_ENV_DIR"
  fi
  echo "vLLM $VLLM_VERSION 을 $VLLM_ENV_DIR 에 설치합니다."
  uv pip install --python "$VLLM_PYTHON" "vllm==$VLLM_VERSION"

  local source_file
  source_file="$(vllm_source_path)"
  [[ -f "$source_file" ]] || {
    echo "오류: Gemma 4 vLLM source를 찾을 수 없습니다: $source_file" >&2
    return 1
  }
  if ! grep -q 'prefix=maybe_prefix(prefix, "embed_vision")' "$source_file"; then
    patch --forward --batch "$source_file" \
      "$PROJECT_DIR/docker/vllm-gemma4-unified-quant.patch"
  fi
  "$VLLM_PYTHON" - "$source_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    "self.embed_vision.embedding_projection.weight.dtype",
    "self.embed_vision.embedding_projection.params_dtype",
)
path.write_text(text, encoding="utf-8")
if 'prefix=maybe_prefix(prefix, "embed_vision")' not in text:
    raise SystemExit("vision quantization patch marker is missing")
if "self.embed_vision.embedding_projection.weight.dtype" in text:
    raise SystemExit("vision projection dtype patch was not applied")
PY
  echo "vLLM native 설치와 Gemma 4 W4A16 호환 patch 적용을 완료했습니다."
}

doctor() {
  local failed=false
  echo "Native runtime 진단"
  for command in curl uv; do
    if command -v "$command" >/dev/null 2>&1; then
      echo "- $command: OK"
    else
      echo "- $command: MISSING"
      failed=true
    fi
  done
  if [[ -x "$NATIVE_PYTHON" ]]; then
    echo "- API/embedding Python: OK ($NATIVE_PYTHON)"
  else
    echo "- API/embedding Python: MISSING (run setup)"
    failed=true
  fi
  if is_true "$MANAGE_DB"; then
    local pg_bin
    pg_bin="$(resolve_postgres_bin 2>/dev/null || true)"
    if [[ -n "$pg_bin" && -x "$pg_bin/postgres" ]]; then
      local pg_config_bin shared_dir
      pg_config_bin="$(command -v pg_config || true)"
      [[ -n "$pg_config_bin" ]] || pg_config_bin="$pg_bin/pg_config"
      shared_dir="$("$pg_config_bin" --sharedir 2>/dev/null || true)"
      if [[ -n "$shared_dir" && -f "$shared_dir/extension/vector.control" ]]; then
        echo "- pgvector: OK"
      else
        echo "- pgvector: MISSING"
        failed=true
      fi
      if [[ "$(id -u)" -eq 0 ]] && (! command -v runuser >/dev/null 2>&1 || ! id "$DB_OS_USER" >/dev/null 2>&1); then
        echo "- PostgreSQL OS user: MISSING ($DB_OS_USER)"
        failed=true
      fi
    else
      echo "- PostgreSQL: MISSING"
      failed=true
    fi
  else
    echo "- PostgreSQL: external"
  fi
  if is_true "$START_LLM"; then
    if [[ -x "$VLLM_BIN" && -x "$VLLM_PYTHON" ]]; then
      echo "- vLLM: OK ($VLLM_BIN)"
    else
      echo "- vLLM: MISSING (run setup-llm)"
      failed=true
    fi
    if [[ -f "$MODEL_PATH/config.json" ]]; then
      echo "- model: OK ($MODEL_PATH)"
    else
      echo "- model: MISSING ($MODEL_PATH)"
      failed=true
    fi
    if command -v nvidia-smi >/dev/null 2>&1; then
      echo "- NVIDIA GPU visibility: OK"
    else
      echo "- NVIDIA GPU visibility: MISSING"
      failed=true
    fi
  else
    echo "- vLLM: external"
  fi
  if is_true "$START_EMBEDDING"; then
    if "$NATIVE_PYTHON" -c 'import sentence_transformers, torch' >/dev/null 2>&1; then
      echo "- embedding dependencies: OK"
    else
      echo "- embedding dependencies: MISSING (run setup)"
      failed=true
    fi
  else
    echo "- embedding: external"
  fi
  [[ "$failed" == false ]]
}

follow_logs() {
  local service="${1:-}"
  if [[ -n "$service" ]]; then
    case "$service" in api|embedding|llm|db) ;; *) usage >&2; return 2 ;; esac
    touch "$(log_file "$service")"
    tail -n 100 -F "$(log_file "$service")"
    return
  fi
  touch "$(log_file api)" "$(log_file embedding)" "$(log_file llm)" "$(log_file db)"
  tail -n 100 -F "$(log_file api)" "$(log_file embedding)" "$(log_file llm)" "$(log_file db)"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

command="${1:-up}"
if [[ "$command" == "--help" || "$command" == "-h" || "$command" == "help" ]]; then
  usage
  exit 0
fi
require_command python3

ensure_env_file
load_config

case "$command" in
  setup)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    setup_native
    ;;
  setup-llm)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    setup_vllm
    ;;
  doctor)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    doctor
    ;;
  up)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    trap 'stop_all' ERR
    start_all
    trap - ERR
    ;;
  foreground)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    trap 'exit 0' INT TERM
    trap 'stop_all' EXIT
    start_all
    while service_running api || [[ -f "$(maintenance_file)" ]]; do
      sleep 5
    done
    echo "오류: API 프로세스가 종료되었습니다." >&2
    exit 1
    ;;
  start-api)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    [[ -x "$NATIVE_PYTHON" ]] || {
      echo "오류: native Python 환경이 없습니다: $NATIVE_PYTHON" >&2
      exit 1
    }
    validate_api_config
    start_api
    wait_for_http api "http://127.0.0.1:$API_PORT/health/ready"
    rm -f "$(maintenance_file)"
    ;;
  stop-api)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    touch "$(maintenance_file)"
    stop_process api
    ;;
  down)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    stop_all
    ;;
  status)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    print_status
    ;;
  logs)
    [[ $# -le 2 ]] || { usage >&2; exit 2; }
    follow_logs "${2:-}"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
