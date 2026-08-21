#!/usr/bin/env bash

set -Eeuo pipefail

# 비어 있거나 없는 persisted 설정만 이미지 기본값으로 복구한다.
initialize_llm_config() {
  local config_path="$1"
  local default_config_path="$2"
  [[ -s "$config_path" ]] && return 0
  mkdir -p "$(dirname "$config_path")"
  install -m 0600 "$default_config_path" "$config_path"
  echo "기본 언어모델 설정을 생성했습니다: $config_path"
}

# 설정과 모델을 검증한 뒤 네이티브 서비스 묶음을 전면 실행한다.
main() {
  if [[ "${NATIVE_DB_PASSWORD:-rag_password}" == "rag_password" \
      && "${ALLOW_INSECURE_DEFAULTS:-false}" != "true" ]]; then
    echo "오류: NATIVE_DB_PASSWORD를 기본값이 아닌 값으로 설정하십시오." >&2
    exit 1
  fi

  # 이미지 갱신 때 유효한 운영자 설정은 덮지 않는다.
  local llm_config_path="${LLM_ENDPOINTS_FILE:-/data/config/llm-endpoints.json}"
  local default_llm_config_path="/app/config/llm-endpoints.default.json"
  initialize_llm_config "$llm_config_path" "$default_llm_config_path"

  # 모델 준비 전에 API 설정 오류를 먼저 확인한다.
  echo "API 설정을 검증합니다."
  env LLM_ENDPOINTS_FILE="$llm_config_path" \
    /app/.venv-native/bin/python -c \
    'from app.services.language_model_service import initialize_configuration; initialize_configuration()'

  # 설정 검증 뒤 모델을 준비해야 잘못된 기동에서 큰 다운로드를 피할 수 있다.
  /usr/local/bin/prepare-model
  exec /app/run-native.sh foreground
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
