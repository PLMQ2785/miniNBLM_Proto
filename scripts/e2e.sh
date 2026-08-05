#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(docker compose -p mininblm-e2e -f docker-compose.e2e.yml)

cleanup() {
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

for command in docker curl uv; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

if [[ ! -f sample_fall_prevention.pdf ]]; then
  echo "E2E fixture not found: sample_fall_prevention.pdf" >&2
  exit 1
fi

curl -fsS --max-time 10 http://127.0.0.1:8070/health >/dev/null || {
  echo "Embedding service is not ready on 127.0.0.1:8070" >&2
  exit 1
}
curl -fsS --max-time 10 http://127.0.0.1:8010/v1/models >/dev/null || {
  echo "vLLM service is not ready on 127.0.0.1:8010" >&2
  exit 1
}

cleanup
"${COMPOSE[@]}" up -d --build --wait

export RUN_REAL_E2E=1
export E2E_BASE_URL=http://127.0.0.1:18080
export E2E_DATABASE_DSN=postgresql://rag_e2e_user:rag_e2e_password@127.0.0.1:55433/rag_e2e_db
export E2E_PDF_PATH="$PROJECT_DIR/sample_fall_prevention.pdf"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

uv run pytest tests/e2e -m e2e "$@"
