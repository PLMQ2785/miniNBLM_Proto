#!/usr/bin/env bash

set -Eeuo pipefail

MODEL_PATH="${VLLM_MODEL_PATH:-/data/models/gemma4}"
MODEL_ARCHIVE_URL="${MODEL_ARCHIVE_URL:-}"
MODEL_ARCHIVE_SHA256="${MODEL_ARCHIVE_SHA256:-}"
MODEL_HF_REPO_ID="${MODEL_HF_REPO_ID:-}"
MODEL_HF_REVISION="${MODEL_HF_REVISION:-}"
MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-/data/model-cache}"
MODEL_KEEP_ARCHIVE="${MODEL_KEEP_ARCHIVE:-false}"
MODEL_MARKER_NAME=".mininblm-model.sha256"
MODEL_SOURCE_MARKER_NAME=".mininblm-model.source"

fail() {
  echo "오류: $*" >&2
  exit 1
}

download_archive() {
  local output_path="$1"
  shift
  local -a common_args=(
    --fail --location --show-error
    --retry-delay 2 --retry-all-errors --connect-timeout 30
  )

  if curl "${common_args[@]}" --retry 1 --output "$output_path" "$@"; then
    return
  fi

  echo "기본 DNS 다운로드에 실패하여 DNS-over-HTTPS로 재시도합니다." >&2
  curl "${common_args[@]}" --retry 5 \
    --resolve dns.google:443:8.8.8.8 \
    --doh-url https://dns.google/dns-query \
    --output "$output_path" "$@"
}

model_is_complete() {
  local path="$1"
  [[ -f "$path/config.json" ]] && compgen -G "$path/*.safetensors" >/dev/null
}

archive_configured=false
hf_configured=false
[[ -n "$MODEL_ARCHIVE_URL" || -n "$MODEL_ARCHIVE_SHA256" ]] && archive_configured=true
[[ -n "$MODEL_HF_REPO_ID" || -n "$MODEL_HF_REVISION" ]] && hf_configured=true

[[ "$archive_configured" != "true" || "$hf_configured" != "true" ]] || fail \
  "MODEL_ARCHIVE_*와 MODEL_HF_* 다운로드 방식을 동시에 설정할 수 없습니다."

requested_source=""
if [[ "$hf_configured" == "true" ]]; then
  [[ "$MODEL_HF_REPO_ID" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || fail \
    "MODEL_HF_REPO_ID는 owner/repository 형식이어야 합니다."
  [[ "$MODEL_HF_REVISION" =~ ^[A-Fa-f0-9]{40}$ ]] || fail \
    "MODEL_HF_REVISION은 재현 가능한 40자리 commit SHA여야 합니다."
  MODEL_HF_REVISION="${MODEL_HF_REVISION,,}"
  requested_source="hf:$MODEL_HF_REPO_ID@$MODEL_HF_REVISION"
elif [[ "$archive_configured" == "true" ]]; then
  [[ -n "$MODEL_ARCHIVE_URL" ]] || fail "MODEL_ARCHIVE_URL을 설정해야 합니다."
  [[ "$MODEL_ARCHIVE_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || fail \
    "MODEL_ARCHIVE_SHA256은 64자리 SHA-256 값이어야 합니다."
  MODEL_ARCHIVE_SHA256="${MODEL_ARCHIVE_SHA256,,}"
  requested_source="archive:sha256:$MODEL_ARCHIVE_SHA256"
fi

case "$MODEL_KEEP_ARCHIVE" in
  true|false) ;;
  *) fail "MODEL_KEEP_ARCHIVE는 true 또는 false여야 합니다." ;;
esac

model_source_matches() {
  local path="$1"
  if [[ -z "$requested_source" ]]; then
    return 0
  fi
  if [[ -f "$path/$MODEL_SOURCE_MARKER_NAME" ]]; then
    [[ "$(< "$path/$MODEL_SOURCE_MARKER_NAME")" == "$requested_source" ]]
  elif [[ "$archive_configured" == "true" && -f "$path/$MODEL_MARKER_NAME" ]]; then
    [[ "$(< "$path/$MODEL_MARKER_NAME")" == "$MODEL_ARCHIVE_SHA256" ]]
  else
    return 1
  fi
}

if model_is_complete "$MODEL_PATH"; then
  model_source_matches "$MODEL_PATH" || fail \
    "설치된 모델 source가 요청한 source와 다릅니다. 모델을 교체하려면 $MODEL_PATH를 비운 뒤 다시 시작하십시오."
  echo "모델 cache 준비 완료: $MODEL_PATH"
  exit 0
fi

[[ ! -e "$MODEL_PATH" ]] || fail \
  "불완전한 모델 경로가 이미 존재합니다: $MODEL_PATH. 해당 경로를 비운 뒤 다시 시작하십시오."
[[ -n "$requested_source" ]] || fail \
  "모델이 없으므로 MODEL_ARCHIVE_* 또는 MODEL_HF_*를 설정해야 합니다: $MODEL_PATH"
model_parent="$(dirname "$MODEL_PATH")"
model_name="$(basename "$MODEL_PATH")"
mkdir -p "$model_parent" "$MODEL_CACHE_DIR"

exec 9>"$MODEL_CACHE_DIR/.model-download.lock"
flock 9

if model_is_complete "$MODEL_PATH"; then
  model_source_matches "$MODEL_PATH" || fail \
    "설치된 모델 source가 요청한 source와 다릅니다. 모델을 교체하려면 $MODEL_PATH를 비운 뒤 다시 시작하십시오."
  echo "모델 cache 준비 완료: $MODEL_PATH"
  exit 0
fi

if [[ "$hf_configured" == "true" ]]; then
  hf_partial_dir="$MODEL_CACHE_DIR/hf-${MODEL_HF_REPO_ID//\//--}-$MODEL_HF_REVISION.part"
  echo "Hugging Face 모델 snapshot을 다운로드합니다. 중단된 파일이 있으면 이어받습니다."
  hf download "$MODEL_HF_REPO_ID" \
    --revision "$MODEL_HF_REVISION" \
    --local-dir "$hf_partial_dir"
  model_is_complete "$hf_partial_dir" || fail \
    "Hugging Face snapshot에서 config.json 또는 Safetensors weight를 찾을 수 없습니다."
  rm -rf "$hf_partial_dir/.cache"
  printf '%s\n' "$requested_source" > "$hf_partial_dir/$MODEL_SOURCE_MARKER_NAME"
  mv "$hf_partial_dir" "$MODEL_PATH"
  echo "모델 설치 완료: $MODEL_PATH"
  exit 0
fi

archive_path="$MODEL_CACHE_DIR/$MODEL_ARCHIVE_SHA256.archive"
partial_path="$archive_path.part"

archive_matches() {
  local path="$1"
  printf '%s  %s\n' "$MODEL_ARCHIVE_SHA256" "$path" | sha256sum --check --status
}

if [[ -f "$archive_path" ]] && ! archive_matches "$archive_path"; then
  echo "checksum이 다른 cache archive를 제거합니다."
  rm -f "$archive_path"
fi

if [[ ! -f "$archive_path" ]]; then
  echo "모델 archive를 다운로드합니다. 중단된 파일이 있으면 이어받습니다."
  if ! download_archive "$partial_path" \
      --continue-at - "$MODEL_ARCHIVE_URL"; then
    if [[ -s "$partial_path" ]]; then
      echo "이어받기에 실패하여 처음부터 다시 다운로드합니다."
      rm -f "$partial_path"
      download_archive "$partial_path" "$MODEL_ARCHIVE_URL"
    else
      exit 1
    fi
  fi
  if ! archive_matches "$partial_path"; then
    rm -f "$partial_path"
    fail "다운로드한 모델 archive의 SHA-256 checksum이 일치하지 않습니다."
  fi
  mv "$partial_path" "$archive_path"
  echo "모델 archive checksum 확인 완료."
fi

extract_dir="$(mktemp -d "$model_parent/.${model_name}.extract.XXXXXX")"
install_dir="$model_parent/.${model_name}.install.$$"
cleanup() {
  rm -rf "$extract_dir" "$install_dir"
}
trap cleanup EXIT

echo "모델 archive를 압축 해제합니다."
tar --extract --file "$archive_path" --directory "$extract_dir" \
  --no-same-owner --no-same-permissions

mapfile -d '' config_files < <(
  find "$extract_dir" -mindepth 1 -maxdepth 2 -type f -name config.json -print0
)
[[ ${#config_files[@]} -eq 1 ]] || fail \
  "모델 archive에는 root 또는 단일 최상위 디렉터리 안의 config.json이 정확히 하나 있어야 합니다."
source_dir="$(dirname "${config_files[0]}")"
compgen -G "$source_dir/*.safetensors" >/dev/null || fail \
  "모델 archive에서 Safetensors weight를 찾을 수 없습니다."

mv "$source_dir" "$install_dir"
printf '%s\n' "$MODEL_ARCHIVE_SHA256" > "$install_dir/$MODEL_MARKER_NAME"
printf '%s\n' "$requested_source" > "$install_dir/$MODEL_SOURCE_MARKER_NAME"
mv "$install_dir" "$MODEL_PATH"

if [[ "$MODEL_KEEP_ARCHIVE" == "false" ]]; then
  rm -f "$archive_path"
fi

trap - EXIT
rm -rf "$extract_dir"
echo "모델 설치 완료: $MODEL_PATH"
