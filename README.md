# PDF RAG Assistant

PDF 문서를 업로드하고, 문서에 근거한 답변과 실제로 인용한 원문 페이지 출처를
제공하는 범용 RAG 서비스입니다.

## 구성

```text
Browser
  -> api        FastAPI API + Vanilla HTML/CSS/JS Web UI
       -> db    PostgreSQL 17 + pgvector
       -> embedding  BGE-M3 embedding service
       -> llm   vLLM OpenAI-compatible Gemma 4 endpoint
```

런타임은 `api`, `db`, `embedding`, `llm` 네 서비스로 구성됩니다. Docker Compose
실행과 Docker를 사용할 수 없는 서버용 비컨테이너 실행을 모두 지원합니다. Web
UI는 API 서비스가 정적 파일로 제공하므로 별도 프런트엔드 빌드가 없습니다.

## 사전 준비

- NVIDIA GPU와 호스트 드라이버
- 프로젝트 루트의 Gemma 4 12B W4A16 모델 디렉터리
- Docker 실행: Docker Engine, Docker Compose, NVIDIA Container Toolkit
- 비컨테이너 실행: Python 3.12, `uv`, PostgreSQL 17와 pgvector, `curl`, `patch`

기본 모델 경로는 `./google/gemma-4-12B-it-W4A16`입니다. 다른 위치를 사용하려면 `.env`의 `VLLM_MODEL_PATH`를 변경합니다.
12B·31B runtime의 기본 `VLLM_MAX_MODEL_LEN`은 `16384`입니다. Vast.ai Template처럼
외부 환경변수가 같은 key를 지정하면 image 기본값보다 우선하므로 배포 환경도
`VLLM_MAX_MODEL_LEN=16384`로 맞춰야 합니다.

API가 사용할 OpenAI 호환 모델 endpoint는 `config/llm-endpoints.json`에 등록합니다.
`default_endpoint`는 사용자가 아직 선택하지 않았거나 등록 endpoint가 사라졌을 때의
fallback key입니다. 각 endpoint는 `key`, `display_name`, `base_url`, `model`,
`supports_vision`, `authentication`을 가집니다. 로그인한 모든 사용자는 작업공간
상단의 **언어모델** 선택 메뉴에서 자신의 endpoint를 전환할 수 있으며 선택은
PostgreSQL에 저장됩니다. 유효한 JSON 변경은 다음 요청부터 자동 적용됩니다.

Docker 실행의 기본 `VISION_CAPTION_MODE=disabled`는 검증된 text-only 경로를
유지합니다. `risk_only`는 텍스트만으로 불완전한 페이지, 표, 도형이 많은 mixed
페이지를 선택하고 `all_visual`은 시각 요소가 검출된 모든 페이지를 처리합니다.
Caption은 페이지당 이미지 1장을 순차 처리하므로 큰 PDF의 최초 인덱싱과
재인덱싱 시간이 늘어납니다.

## 원샷 통합 컨테이너

`Dockerfile.all-in-one`은 PostgreSQL 17+pgvector, BGE-M3, vLLM 0.25.0,
Gemma 4 호환 patch, FastAPI와 Web UI를 이미지 하나에 넣되 모델 weight는 포함하지
않습니다. 컨테이너 내부에서는
DB·embedding·LLM은 loopback에만 bind하고 API만
`0.0.0.0:8080`에 공개합니다.

공개 Hugging Face model repository와 변경되지 않는 40자리 commit SHA를 설정합니다.
12B example은 검증된 repository revision을 기본값으로 제공합니다. archive를 사용할
때는 `MODEL_HF_*` 대신 직접 다운로드 URL과 SHA-256을 설정합니다.

```bash
cp .env.all-in-one.example .env.all-in-one
# DB 비밀번호와 모델 source 설정을 확인
./run_aio.sh

./run_aio.sh status
./run_aio.sh logs
./run_aio.sh down
```

첫 기동 시 Entrypoint가 Hugging Face snapshot을 `/data/model-cache`에 이어받거나
archive를 이어받아 SHA-256을 검증합니다. `config.json`과 Safetensors를 확인한
뒤에만 `/data/models/gemma4`로 원자적으로 설치합니다. 이후 기동은 `/data`의
설치된 모델을 재사용하므로 다시 다운로드하지 않습니다.

운영 데이터, 모델, 업로드 PDF, BGE-M3 cache와 로그는 `mininblm_data` volume에
보존됩니다. `NATIVE_DB_PASSWORD`는 기본값 사용을 거부하므로
`.env.all-in-one`에서 반드시 변경해야 합니다. 모델 weight가 Docker build context와
image layer에서 제외되어 12B·31B image는 런타임 코드 차이만 가집니다.

### Gemma 4 31B W4A16 variant

31B variant는 직접 양자화한 compressed-tensors `pack-quantized` W4A16 archive의
직접 다운로드 URL과 SHA-256을 `.env.all-in-one-31b`에 설정합니다. 기존 checkpoint의
10개 Safetensors weight 합은 `19,073,960,528` bytes입니다. 모델은 첫 실행에서
`/data/models/gemma4`에 설치되고 이후 재사용됩니다.
배포 image는 `cpsu/mininblm:0.1.5-gemma4-31b-w4a16`이며 12B `0.1.5`와 동일하게
Hugging Face snapshot downloader와 소유권 변경 제한 storage 대응을 포함합니다.
현재 Google Drive의 `gemma-4-31B-it-W4A16.tar` archive SHA-256은
`1a28093ac67542780473b4c74f659fb3988d7c69e1fbf974772b2ab94c0f6ebf`입니다.

```bash
cp .env.all-in-one-31b.example .env.all-in-one-31b
# NATIVE_DB_PASSWORD, MODEL_ARCHIVE_URL, MODEL_ARCHIVE_SHA256과 GPU 설정을 변경

# 이미지 build만 수행
docker compose --env-file .env.all-in-one-31b \
  -f docker-compose.all-in-one.yml build mininblm
docker push cpsu/mininblm:0.1.5-gemma4-31b-w4a16

# 배포 서버에서 실행
AIO_ENV_FILE=.env.all-in-one-31b ./run_aio.sh --no-build
```

31B 환경 예시의 기본 배포 대상은 NVIDIA H200 1장입니다. BGE-M3도 GPU에서
실행하며 vLLM VRAM 목표는 `0.70`, 최대 활성 sequence는 8개입니다. 이 31B 조합은
이번 변경에서 기동하거나 추론하지 않았습니다. `VLLM_MAX_NUM_SEQS`는 전체 사용자
수가 아니라 동시에 GPU scheduler에 올라가는 요청 수의 상한입니다.

```bash
docker compose --env-file .env.all-in-one \
  -f docker-compose.all-in-one.yml build mininblm
docker tag cpsu/mininblm:0.1.5 cpsu/mininblm:0.1.5-gemma4-12b-w4a16
docker login
docker push cpsu/mininblm:0.1.5
docker push cpsu/mininblm:0.1.5-gemma4-12b-w4a16

# 배포 서버의 .env.all-in-one에서 같은 image를 지정
export MININBLM_ALL_IN_ONE_IMAGE=cpsu/mininblm:0.1.5
./run_aio.sh --no-build
```

컨테이너 내부 백업·검증·복원은 다음과 같습니다. bundle은
`mininblm_data` volume의 `/data/backups`에 남습니다.

```bash
docker compose -f docker-compose.all-in-one.yml exec mininblm /app/backup.sh
docker compose -f docker-compose.all-in-one.yml exec mininblm \
  /app/restore.sh --verify-only /data/backups/mininblm-backup-<timestamp>.tar.gz
docker compose -f docker-compose.all-in-one.yml exec mininblm \
  /app/restore.sh --yes /data/backups/mininblm-backup-<timestamp>.tar.gz
```

## Docker 빠른 시작

```bash
cp .env.example .env
./run.sh
```

`run.sh`는 네 컨테이너 빌드·기동과 API·embedding·LLM 준비 확인을 순서대로
수행합니다. API entrypoint가 서버 시작 전에 DB migration을 적용합니다. 이후
재빌드 없이 시작하려면 `./run.sh --no-build`를 사용합니다.

LLM은 최초 모델 적재와 커널 컴파일에 시간이 걸릴 수 있습니다. 준비가 끝난 후 브라우저에서 다음 주소를 엽니다.

- 같은 Linux/WSL 또는 Windows host: `http://localhost:8080/`
- mirrored mode에서 다른 LAN 장치: `http://<Windows_HOST_IP>:8080/`

Windows Host IP는 Windows PowerShell에서 확인합니다. Docker와 WSL 가상
어댑터가 아닌 실제 Wi-Fi 또는 Ethernet 어댑터의 IPv4 주소를 사용합니다.

```powershell
ipconfig
```

Web UI에서 사용자명과 비밀번호로 계정을 만든 뒤 PDF를 추가합니다. 상태가
`인덱싱 완료`가 되면 별도 선택 없이 전체 문서를 대상으로 질의할 수 있습니다.
왼쪽 목록에서 특정 PDF를 선택하면 검색과 후속 질문이 해당 문서 안으로
제한되며, `전체 문서`를 선택하면 다시 기존 전체 검색으로 돌아갑니다. 문서와
대화는 로그인한 사용자별로 분리되며, 답변 아래의 페이지 버튼을 누르면 원본
PDF의 해당 페이지가 열립니다. 대화는 전체 또는 선택 문서 범위에 귀속되어
저장되고, 로그인하거나 새로고침하면 가장 최근 대화와 질의 범위가 함께
복원됩니다. 작업공간 상단에서 새 대화를 시작하거나 이전 대화로 전환·삭제할
수 있습니다. `계정` 화면에서는 일반 사용자도 현재
비밀번호를 변경하거나, 비밀번호와 사용자명을 다시 확인한 뒤 계정과 소유
데이터를 모두 삭제할 수 있습니다.

기본 관리자 계정은 없습니다. 최초 관리자 계정이 필요하면 첫 실행 전에 `.env`에
`BOOTSTRAP_ADMIN_USERNAME`과 `BOOTSTRAP_ADMIN_PASSWORD`를 모두 설정합니다.
임시 비밀번호는 8자 이상이며 영문 대·소문자, 숫자, 기호 중 3종 이상을 사용해야
합니다. 최초 로그인 후에는 문서·채팅·관리자 기능에 접근하기 전에 Web UI에서
새 비밀번호로 변경해야 합니다. 변경한 비밀번호는 이후 재시작 시 환경변수 값으로
되돌아가지 않습니다.

관리자는 `관리` 화면에서 일반 사용자의 임시 비밀번호를 설정할 수 있습니다.
재설정 즉시 해당 사용자의 모든 로그인 세션이 폐기되며, 사용자는 임시 비밀번호로
로그인한 뒤 새 비밀번호로 변경해야 문서와 채팅에 접근할 수 있습니다.

관리자는 같은 `관리` 화면에서 OpenAI 호환 LLM endpoint를 추가·편집·삭제하고
기본값을 지정할 수 있습니다. `config/llm-endpoints.json`이 유일한 endpoint
원본이며 DB에는 사용자별 선택 key만 저장됩니다. 관리자 저장은 최신 파일
revision을 확인한 뒤 임시 파일과 원자적 rename으로 반영됩니다. 활성 endpoint는
저장 전에 `/models` 응답에 설정한 model ID가 있는지 검증합니다.

API는 새 요청마다 JSON과 credential master key의 변경을 확인합니다. 변경된 설정은
다음 요청부터 적용되며 이미 진행 중인 채팅·문서 처리는 시작할 때 고정한 endpoint
snapshot을 계속 사용합니다. 삭제되거나 비활성화된 endpoint를 선택했던 사용자는
다음 요청에서 기본 endpoint를 사용합니다. 다른 사용자의 선택 목록은 Web UI를
새로고침하면 갱신됩니다.

인증이 필요 없는 endpoint는 `authentication`을 `none`으로 지정합니다. 인증이
필요하면 관리 화면에서 `managed`를 선택하고 API key를 입력합니다. API는 key를
자동 생성한 Fernet master key로 암호화하며 endpoint JSON에는
`api_key_ciphertext`만 저장합니다. 평문 key와 암호문은 관리 API 응답이나 Web UI에
노출되지 않습니다. 편집할 때 API key를 비워 두면 기존 credential을 유지하고 새
값을 입력하면 교체합니다.

```json
{
  "default_endpoint": "remote",
  "endpoints": [
    {
      "key": "remote",
      "display_name": "Remote model",
      "base_url": "https://llm.example/v1",
      "authentication": "none",
      "model": "remote-model",
      "supports_vision": false,
      "enabled": true
    }
  ]
}
```

기본 Docker 구성은 `./config` 디렉터리를 API의 `/app/config`에 쓰기 가능하게
mount합니다. Credential master key는 기본적으로
`./data/secrets/llm/master.key`에 0600 권한으로 자동 생성됩니다. 통합
컨테이너에서는 endpoint JSON과 master key가 각각
`/data/config/llm-endpoints.json`, `/data/secrets/llm/master.key`에 영속화됩니다.
통합 컨테이너는 persisted endpoint 파일이 없거나 0 byte이면 이미지 기본 설정을
복구합니다. 내용이 있는 운영자 파일은 검증에 실패해도 자동으로 덮어쓰지 않습니다.
암호화된 credential이 있는 상태에서 master key를 잃으면 안전을 위해 설정 로드가
실패하므로 endpoint JSON과 master key를 함께 백업해야 합니다.

기존 일반 계정을 추가 관리자로 지정할 때는 CLI를 사용합니다.

```bash
docker compose exec api python -m app.cli.set_admin <username>
# 비컨테이너 실행
.venv-native/bin/python -m app.cli.set_admin <username>
```

CLI로 승격한 계정도 다음 로그인에서 안전한 비밀번호로 변경해야 합니다. LAN
외부에 서비스를 노출하기 전에는 HTTPS를 적용하고 `AUTH_COOKIE_SECURE=true`로
설정합니다.

## Docker 없는 서버에서 실행

대여 서버 자체가 컨테이너라 Docker-in-Docker를 사용할 수 없는 경우 네 서비스를
일반 프로세스로 실행합니다. `run-native.sh`는 Docker 명령을 호출하지 않으며,
systemd 없이 PostgreSQL, embedding, vLLM, API의 PID와 로그를 직접 관리합니다.

Ubuntu/Debian 계열 서버에는 PostgreSQL 17 server/client와 PostgreSQL 17용
pgvector extension이 필요합니다. PGDG 저장소를 구성한 환경의 패키지 예시는
`postgresql-17`, `postgresql-client-17`, `postgresql-17-pgvector`입니다.
외부 PostgreSQL을 사용하면 로컬 PostgreSQL 패키지는 생략할 수 있습니다.

```bash
cp .env.example .env

# API + BGE-M3 환경
./run-native.sh setup

# 별도 vLLM 환경과 Gemma 4 W4A16 호환 patch
./run-native.sh setup-llm

./run-native.sh doctor
./run-native.sh foreground
```

`foreground`는 대여 서버 컨테이너의 entrypoint/command에 적합하며 SIGTERM을 받으면
관리 중인 프로세스를 종료합니다. SSH 세션에서 background 실행할 때는 다음 명령을
사용합니다.

```bash
./run-native.sh up
./run-native.sh status
./run-native.sh logs
./run-native.sh down
```

서버 제공 PostgreSQL, embedding 또는 OpenAI 호환 LLM endpoint를 사용하려면
`.env`에서 해당 로컬 프로세스를 끕니다.

```dotenv
NATIVE_MANAGE_DB=false
NATIVE_START_EMBEDDING=false
NATIVE_START_LLM=false
DATABASE_URL=postgresql+psycopg://user:password@db.example:5432/rag_db
EMBEDDING_BASE_URL=https://embedding.example
LLM_ENDPOINTS_FILE=./config/llm-endpoints.remote.json
NATIVE_LLM_HEALTH_URL=https://llm.example/v1/models
```

외부 컨테이너에서 GPU 프로세스를 직접 실행하려면 서버 사업자가 그 컨테이너에
NVIDIA device와 driver library를 전달해야 합니다. `nvidia-smi`가 컨테이너
안에서 실패하면 vLLM과 BGE-M3도 로컬로 실행할 수 없습니다. 영속화가 필요한
경로는 `.native/`의 PostgreSQL·로그·cache·uploads와 모델 디렉터리입니다.

## 로컬 API 개발

DB, embedding, LLM은 컨테이너로 실행하고 API만 호스트에서 구동할 수 있습니다.
기본 `dev` dependency group은 API group과 pytest를 포함하며 Torch/CUDA stack은
설치하지 않습니다.

```bash
cp .env.example .env
docker compose up -d db embedding
docker compose --profile llm up -d llm
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8080
```

`pyproject.toml`의 dependency group은 다음처럼 분리되어 있습니다.

| Group | 용도 |
|---|---|
| `common` | FastAPI, Pydantic settings, Uvicorn |
| `api` | DB, PDF, 인증, embedding/LLM HTTP client |
| `embedding` | Sentence Transformers, Torch/CUDA |
| `dev` | API group과 pytest를 포함한 기본 로컬 개발 환경 |

Dockerfile은 API에 `uv sync --frozen --only-group api`, embedding에
`uv sync --frozen --only-group embedding`을 사용합니다. 빌드 후 그룹 분리를
다시 확인하려면 다음 명령을 실행합니다.

```bash
./scripts/check-image-dependencies.sh
```

## 기본 점검

```bash
curl http://localhost:8080/health
curl http://localhost:8080/health/ready
curl http://localhost:8080/metrics
curl http://localhost:8070/health
curl http://localhost:8010/v1/models
curl http://localhost:8080/documents
```

실행 관리 명령:

```bash
./run.sh status
./run.sh logs
./down.sh
```

`down.sh`는 네 컨테이너를 모두 종료하지만 PostgreSQL volume, Hugging Face cache와 `data/`의 업로드 PDF는 삭제하지 않습니다.

DB와 업로드 PDF를 하나의 검증 가능한 bundle로 백업합니다.

```bash
./backup.sh
./restore.sh --verify-only backups/mininblm-backup-<timestamp>.tar.gz
# 비컨테이너 PostgreSQL/API
RUNTIME_MODE=native ./backup.sh
RUNTIME_MODE=native ./restore.sh --verify-only backups/mininblm-backup-<timestamp>.tar.gz
```

실제 복원은 현재 DB와 업로드 PDF를 교체하므로 검증을 마친 bundle에만 명시적으로
`--yes`를 사용합니다. 복원 중 오류가 발생하면 작업 직전 snapshot으로
rollback하고 API를 다시 시작합니다.

```bash
./restore.sh --yes backups/mininblm-backup-<timestamp>.tar.gz
# 비컨테이너 PostgreSQL/API
RUNTIME_MODE=native ./restore.sh --yes backups/mininblm-backup-<timestamp>.tar.gz
```

## 자동화 테스트

전체 단위·통합 테스트는 다음 명령으로 실행합니다.

```bash
./scripts/test.sh -q
```

스크립트는 `docker-compose.test.yml`의 임시 PostgreSQL/pgvector DB를
`127.0.0.1:55432`에서 시작하고 migration과 pytest를 실행한 뒤 DB를 자동으로
종료합니다. 운영 DB, 업로드 PDF, GPU, embedding 및 LLM 서비스는 사용하지
않습니다. 단위 테스트만 빠르게 실행할 때는 다음 명령을 사용합니다.

```bash
uv run pytest tests/unit -q
```

실제 embedding과 vLLM까지 포함한 E2E smoke 테스트는 네 서비스가 실행 중인
상태에서 별도로 수행합니다.

```bash
./scripts/e2e.sh -q
```

이 스크립트는 실제 `embedding:8070`, `llm:8010`을 사용하되 API는 `18080`,
tmpfs 테스트 DB는 `55433`에 따로 기동합니다. pytest도 같은 host network의
전용 API 컨테이너 안에서 실행하므로 WSL의 Docker port 전달 방식에 의존하지
않습니다. 운영 DB와 업로드 문서는 사용하지 않습니다. 샘플 PDF의 파싱·임베딩·
검색·스트리밍 답변·실제 인용 출처와 자료 외 질문의 근거 제한 동작을
검증합니다.

실제 BGE-M3를 사용해 5개 preset과 4개 검색 알고리즘의 Recall@5, MRR와
retrieval 지연을 비교할 때는 다음 명령을 사용합니다. LLM은 필요하지 않으며
전용 tmpfs DB를 사용합니다.

```bash
./scripts/benchmark-retrieval.sh
```

Dense와 Hybrid 후보는 기존 BGE-M3 cosine으로 재정렬합니다. 관련성 점수는
원질문 70%와 goal 검색어의 최대값 30%를 결합하고, 최종 점수는 이 관련성 80%와
기존 검색 순위 20%를 사용합니다. 고유 `goal_id`별 최상위 후보를 최종 Context에
하나 이상 보존하며 embedding 재정렬 실패 시 기존 검색 순위를 유지합니다.

로컬 `sample/`의 실제 PDF를 사용해 복합·다층 추론과 text-only 한계를
문서군별로 평가할 때는 다음 명령을 사용합니다. 실제 embedding과 LLM을
사용하지만 전용 tmpfs DB에서 실행됩니다.

```bash
./scripts/benchmark-reasoning.sh --group Manual
./scripts/benchmark-reasoning.sh --group OpenSWDesign
./scripts/benchmark-reasoning.sh --group OpenSWUnderstand
```

실패 경계 사례의 반복 실행은 `--case`, `--iterations`, `--corpus-mode combined`를
함께 사용합니다. 2026-08-19 검증에서는 visual-only 2개 사례가 각각 3/3으로
명시적 거부와 빈 source를 유지했고, 3일 지연 정량 사례가 `-5% × 3 = -15%`와
모델 불일치의 정량 근거 부재를 3/3으로 구분했습니다. 실제 Gemma 4 planner의
11개 fixture 응답도 모두 원자적 goal plan으로 정규화됐습니다.

회원가입, 문서 업로드와 질문 요청 예시:

```bash
curl -c session.cookie \
  -H "Content-Type: application/json" \
  -d '{"username":"student01","password":"change-this-password"}' \
  http://localhost:8080/auth/register

curl -b session.cookie \
  -F "file=@sample.pdf;type=application/pdf" \
  http://localhost:8080/documents

curl -b session.cookie \
  -H "Content-Type: application/json" \
  -d '{"question":"전체 자료의 핵심 내용을 설명해 주세요."}' \
  http://localhost:8080/chat

curl -N -b session.cookie \
  -H "Content-Type: application/json" \
  -d '{"document_id":<DOCUMENT_ID>,"question":"선택한 자료의 핵심 내용을 설명해 주세요."}' \
  http://localhost:8080/chat/stream
```

## 문서

- [Custom image 및 RunPod 배포](custom_image.md)

## 현재 MVP 범위

- PDF 추가·삭제, 텍스트 추출, page 단위 text/Vision caption chunking 및 BGE-M3 embedding
- 50MiB PDF 파일·51MiB 전체 multipart request 제한과 PDF 시그니처·구조·암호화 검증
- 공개 회원가입, 로그인·로그아웃과 사용자별 문서·대화 격리
- 일반 사용자 비밀번호 변경·다른 세션 폐기와 사용자 소유 데이터 회원탈퇴
- 명시적 관리자 bootstrap, 최초 로그인 비밀번호 변경 강제와 관리자 지원 비밀번호 재설정
- pgvector Dense, PostgreSQL FTS, pg_trgm 및 RRF Hybrid 검색
- Dense/Hybrid 후보의 BGE-M3 cosine 재정렬과 goal별 최상위 후보 보존
- 전체 indexed 문서 또는 사용자가 선택한 문서 하나를 대상으로 하는 RAG 검색
- 좌표 기반 PDF 텍스트 순서, 반복 머리말·꼬리말 제거와 표 행·열 보존
- 페이지별 시각 의존도 감지, 선택적 Gemma 4 구조화 caption과 시각 근거가 검색되지
  않은 화면·도표 질문의 명시적 거부
- 고유 `goal_id`가 있는 최대 4개 원자적 근거 목표, goal별 후보 보존과 부분 근거 답변
- 전체·문서별 대화 세션 저장, 최근 대화·질의 범위 자동 복원과 직전 대화 기반 질의 재작성
- 여러 OpenAI 호환 endpoint 등록과 기본 endpoint 선택을 통한 Gemma 4 12B W4A16 답변 생성
- SSE 기반 답변 스트리밍과 완료된 대화의 이력 저장
- 모델 context 초과 시 출력 예산 조정·입력 축소·최종 근거 발췌로 SSE 응답 완료
- 모델이 실제 인용한 `Source N`만 `문서명 · 페이지` 출처로 표시하고 원본 PDF 연결
- 반응형 Web UI와 문서 처리 상태 polling
- 관리자 청킹 프리셋 5개, 검색 알고리즘 4개와 변경 영향 판정
- API 재시작 시 중단된 PDF 인덱싱과 전체 재인덱싱 자동 복구
- DB, embedding, vLLM 통합 readiness와 Docker 시작 상태 연동
- JSON 구조화 로그, request ID와 Prometheus HTTP·검색·LLM 지표
- PostgreSQL과 업로드 PDF의 checksum 포함 백업·복원 bundle

기존에 인덱싱한 문서에 새 페이지 품질 메타데이터를 적용하려면 관리자 preset을
다시 적용해 전체 재인덱싱해야 합니다. Vision caption도 이 재인덱싱부터 생성됩니다.
원본 텍스트와 caption은 각각 `text`, `vision_caption` chunk로 분리되지만 둘 다
BGE-M3 텍스트 embedding으로 검색합니다. Scanned PDF 전용 OCR, 영속 작업 queue,
전체 문서군 Vision 품질 benchmark는 후속 범위입니다.
