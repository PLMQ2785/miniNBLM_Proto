#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="${AIO_ENV_FILE:-.env.all-in-one}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.all-in-one.yml)
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-1800}"

usage() {
  cat <<'EOF'
Usage:
  ./run_aio.sh                 Build and start the all-in-one container
  ./run_aio.sh --no-build      Start the registry/local image without building
  ./run_aio.sh pull            Pull the configured registry image
  ./run_aio.sh down            Stop the all-in-one container
  ./run_aio.sh status          Show container status
  ./run_aio.sh logs            Follow container logs
  ./run_aio.sh --help          Show this help

Environment:
  AIO_ENV_FILE=.env.all-in-one  Compose environment file
  STARTUP_TIMEOUT=1800          Readiness timeout in seconds
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "오류: '$1' 명령을 찾을 수 없습니다." >&2
    exit 1
  fi
}

env_value() {
  local key="$1"
  local default_value="${2:-}"
  local name value
  while IFS='=' read -r name value; do
    [[ "$name" == "$key" ]] || continue
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    printf '%s' "$value"
    return
  done <"$ENV_FILE"
  printf '%s' "$default_value"
}

ensure_environment_file() {
  require_command docker
  docker compose version >/dev/null
  if [[ ! -f "$ENV_FILE" ]]; then
    cp .env.all-in-one.example "$ENV_FILE"
    echo ".env.all-in-one.example을 복사해 $ENV_FILE 을 생성했습니다."
  fi
}

validate_start_configuration() {
  local password model_source model_repository model_path
  local admin_username admin_password normalized_username normalized_password
  local password_classes=0
  password="${NATIVE_DB_PASSWORD:-$(env_value NATIVE_DB_PASSWORD)}"
  if [[ -z "$password" || "$password" == "rag_password" \
      || "$password" == "change-this-database-password" ]]; then
    echo "오류: $ENV_FILE 의 NATIVE_DB_PASSWORD를 안전한 값으로 변경하십시오." >&2
    exit 1
  fi

  admin_username="${BOOTSTRAP_ADMIN_USERNAME:-$(env_value BOOTSTRAP_ADMIN_USERNAME)}"
  admin_password="${BOOTSTRAP_ADMIN_PASSWORD:-$(env_value BOOTSTRAP_ADMIN_PASSWORD)}"
  if [[ -n "$admin_username" || -n "$admin_password" ]]; then
    if [[ -z "$admin_username" || -z "$admin_password" ]]; then
      echo "오류: BOOTSTRAP_ADMIN_USERNAME과 BOOTSTRAP_ADMIN_PASSWORD를 함께 설정하십시오." >&2
      exit 1
    fi
    normalized_username="${admin_username,,}"
    normalized_password="${admin_password,,}"
    if [[ ! "$normalized_username" =~ ^[a-z0-9_.-]{3,32}$ ]]; then
      echo "오류: BOOTSTRAP_ADMIN_USERNAME은 영문 소문자·숫자·_.- 조합의 3~32자여야 합니다." >&2
      exit 1
    fi
    if (( ${#admin_password} < 8 )); then
      echo "오류: BOOTSTRAP_ADMIN_PASSWORD는 8자 이상이어야 합니다." >&2
      exit 1
    fi
    case "$normalized_password" in
      admin|adminadmin|admin123|admin1234|changeme|password|password123|password1234)
        echo "오류: BOOTSTRAP_ADMIN_PASSWORD가 너무 흔한 비밀번호입니다." >&2
        exit 1
        ;;
    esac
    if [[ "$normalized_password" == *"$normalized_username"* ]]; then
      echo "오류: BOOTSTRAP_ADMIN_PASSWORD에 관리자 사용자명을 포함할 수 없습니다." >&2
      exit 1
    fi
    [[ "$admin_password" =~ [[:lower:]] ]] && ((password_classes += 1))
    [[ "$admin_password" =~ [[:upper:]] ]] && ((password_classes += 1))
    [[ "$admin_password" =~ [[:digit:]] ]] && ((password_classes += 1))
    [[ "$admin_password" =~ [^[:alnum:]] ]] && ((password_classes += 1))
    if (( password_classes < 3 )); then
      echo "오류: BOOTSTRAP_ADMIN_PASSWORD는 영문 소문자·대문자·숫자·기호 중 3종 이상을 사용해야 합니다." >&2
      exit 1
    fi
  fi

  model_source="${MININBLM_MODEL_VOLUME:-$(env_value MININBLM_MODEL_VOLUME mininblm_models)}"
  model_repository="${MODEL_REPOSITORY:-$(env_value MODEL_REPOSITORY)}"
  if [[ "$model_source" == /* || "$model_source" == ./* || "$model_source" == ../* ]]; then
    model_path="$model_source"
    if [[ "$model_path" != /* ]]; then
      model_path="$PROJECT_DIR/${model_path#./}"
    fi
    if [[ ! -f "$model_path/config.json" ]]; then
      echo "오류: Gemma 모델의 config.json을 찾을 수 없습니다: $model_path" >&2
      exit 1
    fi
  elif [[ -z "$model_repository" ]]; then
    echo "오류: named model volume을 사용할 때는 MODEL_REPOSITORY를 설정하십시오." >&2
    exit 1
  fi
}

container_state() {
  local container_id
  container_id="$("${COMPOSE[@]}" ps -aq mininblm 2>/dev/null | sed -n '1p')"
  if [[ -z "$container_id" ]]; then
    printf 'missing'
    return
  fi
  docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || printf 'unknown'
}

wait_for_ready() {
  local deadline=$((SECONDS + STARTUP_TIMEOUT))
  local next_notice=$SECONDS
  printf '원샷 통합 컨테이너 준비 대기 중'
  until "${COMPOSE[@]}" exec -T mininblm \
      curl -fsS --max-time 5 http://127.0.0.1:8080/health/ready >/dev/null 2>&1; do
    local state
    state="$(container_state)"
    if [[ "$state" == "exited" || "$state" == "dead" ]]; then
      echo
      echo "오류: 원샷 컨테이너가 '$state' 상태입니다." >&2
      "${COMPOSE[@]}" logs --tail=120 mininblm >&2
      return 1
    fi
    if (( SECONDS >= deadline )); then
      echo
      echo "오류: 준비 시간이 ${STARTUP_TIMEOUT}초를 초과했습니다." >&2
      "${COMPOSE[@]}" logs --tail=120 mininblm >&2
      return 1
    fi
    if (( SECONDS >= next_notice )); then
      printf '.'
      next_notice=$((SECONDS + 10))
    fi
    sleep 3
  done
  echo " 완료"
}

print_access_urls() {
  echo
  echo "원샷 통합 컨테이너가 준비되었습니다."
  echo "Web UI: http://localhost:8080/"
  echo "상태 확인: ./run_aio.sh status"
  echo "로그 확인: ./run_aio.sh logs"
  echo "종료: ./run_aio.sh down"
}

command="${1:-up}"
case "$command" in
  --help|-h|help)
    usage
    exit 0
    ;;
  down|status|logs|pull)
    ensure_environment_file
    case "$command" in
      down) "${COMPOSE[@]}" down ;;
      status) "${COMPOSE[@]}" ps ;;
      logs) "${COMPOSE[@]}" logs -f mininblm ;;
      pull) "${COMPOSE[@]}" pull mininblm ;;
    esac
    exit 0
    ;;
  up)
    build_args=(--build)
    ;;
  --no-build)
    build_args=()
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

ensure_environment_file
validate_start_configuration

echo "원샷 통합 컨테이너를 시작합니다: PostgreSQL, embedding, vLLM, API"
"${COMPOSE[@]}" up -d "${build_args[@]}" mininblm
wait_for_ready
print_access_urls
