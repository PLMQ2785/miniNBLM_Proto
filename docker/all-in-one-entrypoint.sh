#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "${NATIVE_DB_PASSWORD:-rag_password}" == "rag_password" \
    && "${ALLOW_INSECURE_DEFAULTS:-false}" != "true" ]]; then
  echo "오류: NATIVE_DB_PASSWORD를 기본값이 아닌 값으로 설정하십시오." >&2
  exit 1
fi

# 이미지 갱신 때 운영자 설정을 덮지 않도록 최초 한 번만 기본 설정을 복사한다.
LLM_CONFIG_PATH="${LLM_ENDPOINTS_FILE:-/data/config/llm-endpoints.json}"
DEFAULT_LLM_CONFIG_PATH="/app/config/llm-endpoints.default.json"
if [[ ! -f "$LLM_CONFIG_PATH" ]]; then
  mkdir -p "$(dirname "$LLM_CONFIG_PATH")"
  install -m 0600 "$DEFAULT_LLM_CONFIG_PATH" "$LLM_CONFIG_PATH"
  echo "기본 언어모델 설정을 생성했습니다: $LLM_CONFIG_PATH"
fi

# 모델 준비 전에 API 설정 오류를 먼저 확인한다.
echo "API 설정을 검증합니다."
env LLM_ENDPOINTS_FILE="$LLM_CONFIG_PATH" \
  /app/.venv-native/bin/python -c 'from app.config import settings'

# 설정 검증 뒤 모델을 준비해야 잘못된 기동에서 큰 다운로드를 피할 수 있다.
/usr/local/bin/prepare-model


# 모든 선행 준비가 끝난 뒤 네이티브 서비스 묶음을 전면 실행한다.
exec /app/run-native.sh foreground
