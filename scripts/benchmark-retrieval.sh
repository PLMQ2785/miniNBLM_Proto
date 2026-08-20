#!/usr/bin/env bash
# Measure retrieval quality without touching the application database.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(docker compose -p mininblm-benchmark -f docker-compose.benchmark.yml)

cleanup() {
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

for command in docker curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

if [[ ! -f evaluation/retrieval_fall_prevention.json ]]; then
  echo "Evaluation fixture not found" >&2
  exit 1
fi

if ! curl -fsS --max-time 10 http://127.0.0.1:8070/health >/dev/null 2>&1; then
  docker compose -f docker-compose.yml exec -T embedding \
    curl -fsS --max-time 10 http://127.0.0.1:8070/health >/dev/null || {
      echo "Embedding service is not ready on 127.0.0.1:8070" >&2
      exit 1
    }
fi

cleanup
mkdir -p benchmark_results/retrieval
export BENCHMARK_UID="$(id -u)"
export BENCHMARK_GID="$(id -g)"
"${COMPOSE[@]}" build benchmark
"${COMPOSE[@]}" up -d --wait

migration_ready=false
for _ in {1..10}; do
  if "${COMPOSE[@]}" run --rm benchmark alembic upgrade head; then
    migration_ready=true
    break
  fi
  sleep 1
done
if [[ "$migration_ready" != true ]]; then
  echo "Benchmark database did not become ready" >&2
  exit 1
fi

"${COMPOSE[@]}" run --rm benchmark python -m app.evaluation.retrieval_benchmark "$@"
