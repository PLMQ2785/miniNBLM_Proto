#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

repeats="${RERANKER_AB_REPEATS:-3}"
fixture="${RERANKER_AB_FIXTURE:-evaluation/retrieval_work_education.json}"

if [[ ! "$repeats" =~ ^[1-9][0-9]*$ ]]; then
  echo "RERANKER_AB_REPEATS must be a positive integer" >&2
  exit 1
fi
if [[ ! -f "$fixture" ]]; then
  echo "Reranker A/B fixture not found: $fixture" >&2
  exit 1
fi

# Use one stable default matrix when the caller supplies no arguments.
if (($# == 0)); then
  set -- \
    --preset balanced \
    --algorithm dense \
    --algorithm hybrid \
    --warmup 1 \
    --iterations 3 \
    --evaluation-k 5 \
    --minimum-recall 0.8
fi

# Alternate modes so each pair sees the same fixture and arguments.
for ((run = 1; run <= repeats; run++)); do
  for mode in embedding cross_encoder; do
    printf '\n=== Reranker A/B run %d/%d: %s ===\n' "$run" "$repeats" "$mode"
    RERANKER_MODE="$mode" ./scripts/benchmark-retrieval.sh \
      --fixture "$fixture" \
      "$@"
  done
done
