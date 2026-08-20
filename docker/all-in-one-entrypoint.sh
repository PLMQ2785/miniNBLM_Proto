#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "${NATIVE_DB_PASSWORD:-rag_password}" == "rag_password" \
    && "${ALLOW_INSECURE_DEFAULTS:-false}" != "true" ]]; then
  echo "오류: NATIVE_DB_PASSWORD를 기본값이 아닌 값으로 설정하십시오." >&2
  exit 1
fi

# Seed persistent config once; later image upgrades must not overwrite operator changes.
LLM_CONFIG_PATH="${LLM_ENDPOINTS_FILE:-/data/config/llm-endpoints.json}"
DEFAULT_LLM_CONFIG_PATH="/app/config/llm-endpoints.default.json"
if [[ ! -f "$LLM_CONFIG_PATH" ]]; then
  mkdir -p "$(dirname "$LLM_CONFIG_PATH")"
  install -m 0600 "$DEFAULT_LLM_CONFIG_PATH" "$LLM_CONFIG_PATH"
  echo "기본 언어모델 설정을 생성했습니다: $LLM_CONFIG_PATH"
fi

echo "API 설정을 검증합니다."
env LLM_ENDPOINTS_FILE="$LLM_CONFIG_PATH" \
  /app/.venv-native/bin/python -c 'from app.config import settings'

/usr/local/bin/prepare-model


exec /app/run-native.sh foreground
