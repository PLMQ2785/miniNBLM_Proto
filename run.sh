#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(docker compose --profile llm)
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-900}"

usage() {
  cat <<'EOF'
Usage:
  ./run.sh                 Build and start all services
  ./run.sh --no-build      Start all services without building images
  ./down.sh                Stop all services
  ./run.sh down            Stop all services (same operation)
  ./run.sh status          Show service status
  ./run.sh logs            Follow service logs
  ./run.sh --help          Show this help

Environment:
  STARTUP_TIMEOUT=900      Readiness timeout in seconds
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "오류: '$1' 명령을 찾을 수 없습니다." >&2
    exit 1
  fi
}

container_state() {
  local service="$1"
  local container_id
  container_id="$("${COMPOSE[@]}" ps -aq "$service" 2>/dev/null | head -n 1)"
  if [[ -z "$container_id" ]]; then
    printf 'missing'
    return
  fi
  docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || printf 'unknown'
}

wait_for_endpoint() {
  local service="$1"
  local url="$2"
  local label="$3"
  local log_services="${4:-$service}"
  local deadline=$((SECONDS + STARTUP_TIMEOUT))
  local next_notice=$SECONDS

  printf '%s 준비 대기 중' "$label"
  until "${COMPOSE[@]}" exec -T api curl -fsS --max-time 5 "$url" >/dev/null 2>&1; do
    local state
    state="$(container_state "$service")"
    if [[ "$state" == "exited" || "$state" == "dead" ]]; then
      echo
      echo "오류: $label 컨테이너가 '$state' 상태입니다." >&2
      "${COMPOSE[@]}" logs --tail=80 $log_services >&2
      return 1
    fi
    if (( SECONDS >= deadline )); then
      echo
      echo "오류: $label 준비 시간이 ${STARTUP_TIMEOUT}초를 초과했습니다." >&2
      "${COMPOSE[@]}" exec -T api curl -sS --max-time 5 "$url" >&2 || true
      echo >&2
      "${COMPOSE[@]}" logs --tail=80 $log_services >&2
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

# Fail early when the configured model mount is incomplete.
ensure_environment() {
  require_command docker
  docker compose version >/dev/null

  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo ".env.example을 복사해 .env를 생성했습니다."
  fi

  local model_path
  model_path="$(sed -n 's/^VLLM_MODEL_PATH=//p' .env | tail -n 1)"
  model_path="${model_path:-./google/gemma-4-12B-it-W4A16}"
  model_path="${model_path%\"}"
  model_path="${model_path#\"}"

  if [[ "$model_path" != /* ]]; then
    model_path="$PROJECT_DIR/${model_path#./}"
  fi
  if [[ ! -f "$model_path/config.json" ]]; then
    echo "오류: Gemma 모델의 config.json을 찾을 수 없습니다: $model_path" >&2
    echo ".env의 VLLM_MODEL_PATH를 확인하십시오." >&2
    exit 1
  fi
}

print_access_urls() {
  echo
  echo "서비스가 준비되었습니다."
  echo "Web UI (WSL/Linux): http://localhost:8080/"
  echo "Web UI (LAN, mirrored): http://<Windows_HOST_IP>:8080/"
  echo "Windows Host IP는 PowerShell의 ipconfig로 확인하십시오."
  echo "상태 확인: ./run.sh status"
  echo "로그 확인: ./run.sh logs"
  echo "종료: ./down.sh"
}

command="${1:-up}"
case "$command" in
  down)
    require_command docker
    "${COMPOSE[@]}" down
    exit 0
    ;;
  status)
    require_command docker
    "${COMPOSE[@]}" ps
    exit 0
    ;;
  logs)
    require_command docker
    "${COMPOSE[@]}" logs -f api embedding llm db
    exit 0
    ;;
  --help|-h|help)
    usage
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

ensure_environment

echo "네 개 서비스를 시작합니다: db, embedding, llm, api"
"${COMPOSE[@]}" up -d "${build_args[@]}"

wait_for_endpoint \
  api \
  http://127.0.0.1:8080/health/ready \
  "전체 서비스" \
  "api embedding llm db"

print_access_urls
