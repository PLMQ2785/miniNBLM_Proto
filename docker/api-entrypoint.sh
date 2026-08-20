#!/bin/sh
set -eu

# API가 요청을 받기 전에 데이터베이스 스키마를 최신 상태로 맞춘다.
alembic upgrade head
# 마이그레이션이 끝난 뒤 API를 전면 프로세스로 실행한다.
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-access-log
