#!/usr/bin/env bash
# ML 의존성이 임베딩 이미지에만 있는지 확인해 API 이미지를 가볍게 유지한다.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

docker compose run --rm --no-deps api python -c '
import importlib.util
import app.main
import fitz
import openai
import pgvector
import sqlalchemy

for package in ("torch", "sentence_transformers", "transformers"):
    assert importlib.util.find_spec(package) is None, f"{package} must not be installed in the API image"
print("API dependencies: OK; ML stack: absent")
'

docker compose run --rm --no-deps embedding python -c '
import importlib.util

for package in ("torch", "sentence_transformers"):
    assert importlib.util.find_spec(package) is not None, f"{package} is missing from the embedding image"
print("Embedding dependencies: OK")
'

docker image inspect mininblm-api:latest mininblm-embedding:latest \
  --format '{{.RepoTags}} {{.Size}} bytes'
