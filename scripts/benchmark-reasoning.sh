#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE=(
  docker compose
  -p mininblm-reasoning
  -f docker-compose.benchmark.yml
  -f docker-compose.reasoning.yml
)

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

if [[ ! -f evaluation/sample_multilayer_reasoning.json ]]; then
  echo "Reasoning evaluation fixture not found" >&2
  exit 1
fi
if [[ ! -d sample ]]; then
  echo "Local sample PDF directory not found" >&2
  exit 1
fi

if ! curl -fsS --max-time 10 http://127.0.0.1:8070/health >/dev/null 2>&1; then
  docker compose -f docker-compose.yml exec -T embedding \
    curl -fsS --max-time 10 http://127.0.0.1:8070/health >/dev/null || {
      echo "Embedding service is not ready on 127.0.0.1:8070" >&2
      exit 1
    }
fi
if ! curl -fsS --max-time 10 http://127.0.0.1:8010/v1/models >/dev/null 2>&1; then
  docker compose -f docker-compose.yml exec -T llm \
    curl -fsS --max-time 10 http://127.0.0.1:8010/v1/models >/dev/null || {
      echo "vLLM service is not ready on 127.0.0.1:8010" >&2
      exit 1
    }
fi

cleanup
mkdir -p benchmark_results/reasoning
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
  echo "Reasoning benchmark database did not become ready" >&2
  exit 1
fi

"${COMPOSE[@]}" run --rm benchmark python -m app.evaluation.reasoning_benchmark "$@"
