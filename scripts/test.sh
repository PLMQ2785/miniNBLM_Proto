#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(docker compose -p mininblm-test -f docker-compose.test.yml)

cleanup() {
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cleanup
"${COMPOSE[@]}" up -d --wait

export DATABASE_URL="postgresql+psycopg://rag_test_user:rag_test_password@127.0.0.1:55432/rag_test_db"
export UPLOAD_DIR="/tmp/mininblm-test-uploads"
export BOOTSTRAP_ADMIN_USERNAME="admin"
export BOOTSTRAP_ADMIN_PASSWORD="Test!Bootstrap2026"
export MININBLM_TEST_DATABASE="1"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

uv run alembic upgrade head
uv run pytest "$@"
