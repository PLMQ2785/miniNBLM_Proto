# 운영 및 검증 가이드

## 1. 서비스와 포트

| 서비스 | 호스트 포트 | 역할 | GPU |
|---|---:|---|---|
| `api` | 8080 | FastAPI, Web UI, 문서 처리 조정 | 아니요 |
| `db` | 5433 | PostgreSQL 17, pgvector | 아니요 |
| `embedding` | 8070 | BGE-M3 embedding HTTP API | 예 |
| `llm` | 8010 | vLLM OpenAI-compatible API | 예 |

mirrored WSL에서 Windows `localhost` 전달이 Docker bridge publish를 건너뛰는
문제를 피하기 위해 네 컨테이너 모두 host network를 사용합니다. DB,
embedding, LLM은 `127.0.0.1`에만 bind하고 API만 `0.0.0.0:8080`에 bind하므로
외부에는 Web UI/API만 노출됩니다.

Windows Host에 할당된 IPv4 주소로도 접근하려면 `%UserProfile%\.wslconfig`에
다음 설정을 사용하고 PowerShell에서 `wsl --shutdown` 후 WSL을 다시 시작합니다.

```ini
[wsl2]
networkingMode=mirrored

[experimental]
hostAddressLoopback=true
```

## 2. 시작과 종료

전체 서비스를 시작합니다.

```bash
./run.sh
```

스크립트는 `.env`가 없으면 예제에서 생성하고, 모델 경로를 검증한 뒤 네
컨테이너를 시작합니다. API entrypoint가 Alembic migration을 적용하며,
`run.sh`는 DB, embedding, LLM을 종합하는 `/health/ready`가 성공할 때까지
기다립니다. 기본 제한시간은 900초이며 다음과 같이 변경할 수 있습니다.

```bash
STARTUP_TIMEOUT=1200 ./run.sh
./run.sh --no-build
```

상태와 로그를 확인합니다.

```bash
./run.sh status
./run.sh logs
```

서비스를 종료합니다. PostgreSQL과 Hugging Face cache volume, 호스트의 `data/`는 유지됩니다.

```bash
./down.sh
```

모델이 필요 없는 API/DB 개발에서는 LLM profile을 제외할 수 있습니다.

```bash
docker compose up -d db embedding api
```

이 경우 문서 인덱싱은 가능하지만 `/chat`은 별도로 실행 중인 vLLM endpoint가 없으면 실패합니다.

### 2.1 원샷 통합 컨테이너

배포 단위를 하나로 줄일 때는 `Dockerfile.all-in-one`과
`docker-compose.all-in-one.yml`을 사용한다. 이미지 하나가 PostgreSQL,
embedding, vLLM, API를 일반 process로 실행하고 `run-native.sh foreground`가
PID와 SIGTERM 종료 순서를 관리한다.

```bash
cp .env.all-in-one.example .env.all-in-one
# DB 비밀번호와 모델 source 설정을 확인
./run_aio.sh
./run_aio.sh status
./run_aio.sh logs
./run_aio.sh down
```

`mininblm_data` volume에는 PostgreSQL, uploads, BGE-M3 cache, 로그, 백업과
`/data/models/gemma4`의 모델을 보존한다. 모델 weight는 image에 포함하지 않는다.
Entrypoint는 모델이 없을 때 commit SHA로 고정한 Hugging Face snapshot을 이어받거나
`MODEL_ARCHIVE_URL`을 이어받아 `MODEL_ARCHIVE_SHA256`을 검증한다. `config.json`과
Safetensors가 모두 확인된 뒤에만 모델 경로로 원자적으로 이동하므로 중단된
다운로드나 잘못된 archive를 vLLM이 읽지 않는다.

Hugging Face와 archive 방식은 동시에 설정할 수 없다. archive 방식에서
`MODEL_KEEP_ARCHIVE=false`이면 성공 후 archive를 삭제한다. 모델 설치본은 `/data`
volume에 남으므로 재시작과 image 교체 시 다시 다운로드하지 않는다. 다른 모델로
교체하려면 container를 중지하고 `/data/models/gemma4`를 비운 뒤 새 source로
시작한다.

원샷 컨테이너가 root로 실행되더라도 Network Volume은 `chown`을 거부할 수 있다.
runtime은 data 경로 UID와 container 사용자를 대응시키지만, UID가 고정된 root이면
PostgreSQL을 안전하게 실행할 수 없다. 임시 smoke에서는
`NATIVE_DB_DATA_DIR=/var/lib/mininblm/postgres`와
`NATIVE_LOG_DIR=/var/log/mininblm`을 사용한다. 이 경로는 container disk라
stop/restart 시 초기화되므로 영속 운영에서는 외부 PostgreSQL을 사용해야 한다.

`NATIVE_DB_PASSWORD` 기본값은 entrypoint가 거부한다. `run_aio.sh`는
`--no-build`, `pull`, `status`, `logs`, `down` 명령과 readiness 대기를 제공한다.
환경 파일 경로는 `AIO_ENV_FILE`로 바꿀 수 있다.

모델 archive를 외부 storage에 게시하기 전에 모델 재배포 조건과 접근 범위를
확인한다. Google Drive를 사용하면 일반 공유 페이지가 아니라 curl로 파일 본문을
받을 수 있는 직접 다운로드 URL을 설정해야 한다. 대용량 파일의 quota와 throttling을
피하려면 S3/R2 같은 object storage를 우선한다.

```bash
docker compose --env-file .env.all-in-one \
  -f docker-compose.all-in-one.yml build mininblm
docker tag cpsu/mininblm:0.1.4 cpsu/mininblm:0.1.4-gemma4-12b-w4a16
docker login
docker push cpsu/mininblm:0.1.4
docker push cpsu/mininblm:0.1.4-gemma4-12b-w4a16

#### Gemma 4 31B W4A16 variant

31B 배포는 `.env.all-in-one-31b.example`을 기준으로 한다. 직접 양자화한
compressed-tensors `pack-quantized` W4A16 모델 디렉터리를 archive로 만들고
직접 다운로드 URL과 SHA-256을 설정한다. 기존 checkpoint의 10개 Safetensors
weight 합은 `19,073,960,528` bytes다.
현재 Google Drive의 `gemma-4-31B-it-W4A16.tar` archive SHA-256은
`1a28093ac67542780473b4c74f659fb3988d7c69e1fbf974772b2ab94c0f6ebf`다.

```bash
cp .env.all-in-one-31b.example .env.all-in-one-31b
# NATIVE_DB_PASSWORD, MODEL_ARCHIVE_URL, MODEL_ARCHIVE_SHA256, GPU 설정을 변경
docker compose --env-file .env.all-in-one-31b \
  -f docker-compose.all-in-one.yml build mininblm
docker push cpsu/mininblm:0.1.4-gemma4-31b-w4a16

# 원격 서버
AIO_ENV_FILE=.env.all-in-one-31b ./run_aio.sh pull
AIO_ENV_FILE=.env.all-in-one-31b ./run_aio.sh --no-build
```

기본 배포 대상은 NVIDIA H200 1장이다. BGE-M3를 GPU에서 실행하고, 단일 vLLM
인스턴스에 GPU 메모리의 70%를 할당하며 최대 8개 활성 sequence를 continuous
batching으로 처리한다. CPU offload와 tensor parallel은 사용하지 않는다.

### 2.2 Docker 없이 네 서비스 실행

대여 서버가 이미 컨테이너여서 nested container를 만들 수 없으면
`run-native.sh`를 사용한다. 이 경로는 Docker daemon, Docker CLI, systemd를
요구하지 않는다. API와 embedding은 `.venv-native`, vLLM은 dependency 충돌을
피하기 위해 `.venv-vllm`에 분리한다.

필수 시스템 구성:

- Python 3.12와 `uv`
- `curl`, `patch`
- 로컬 DB 사용 시 PostgreSQL 17 server/client와 PostgreSQL 17용 pgvector
- 로컬 GPU 서비스 사용 시 컨테이너 안에서 동작하는 `nvidia-smi`
- `VLLM_MODEL_PATH`의 Gemma 4 W4A16 모델

PGDG 저장소를 사용하는 Ubuntu/Debian의 PostgreSQL 패키지명은 일반적으로
`postgresql-17`, `postgresql-client-17`, `postgresql-17-pgvector`다.
`pg_trgm`은 PostgreSQL contrib extension이며 Alembic이 `vector`와 함께 생성한다.
root로 실행하는 외부 컨테이너에서는 로컬 PostgreSQL만
`NATIVE_DB_OS_USER=postgres` 사용자로 내린다.

```bash
cp .env.example .env
./run-native.sh setup
./run-native.sh setup-llm
./run-native.sh doctor
```

`setup-llm`은 vLLM `0.25.0`을 별도 환경에 설치하고 Docker 이미지에도 사용한
Gemma 4 W4A16 vision quantization 및 projection dtype patch를 같은 source에
적용한다. 설치가 끝나면 background 또는 foreground 중 하나로 시작한다.

```bash
# SSH 세션에서 background 프로세스로 실행
./run-native.sh up
./run-native.sh status
./run-native.sh logs api
./run-native.sh down

# 대여 서버 컨테이너의 command/entrypoint
./run-native.sh foreground
```

`foreground`는 API process를 감시하며 SIGINT/SIGTERM에서 로컬로 관리하는
API, vLLM, embedding, PostgreSQL을 역순으로 종료한다. PostgreSQL data,
Hugging Face cache, PID, 로그, 업로드 원본은 `.native/`에 둔다. 대여 서버
재생성 후에도 필요한 경우 `.native/`와 모델 디렉터리를 영속 volume에 연결한다.

사업자가 제공하는 외부 서비스를 조합할 수도 있다.

```dotenv
NATIVE_MANAGE_DB=false
NATIVE_START_EMBEDDING=false
NATIVE_START_LLM=false
DATABASE_URL=postgresql+psycopg://user:password@db.example:5432/rag_db
EMBEDDING_BASE_URL=https://embedding.example
LLM_ENDPOINTS_FILE=./config/llm-endpoints.remote.json
NATIVE_LLM_HEALTH_URL=https://llm.example/v1/models
```

외부 DB 사용자는 `vector`, `pg_trgm` extension을 생성할 권한이 있어야 한다.
권한이 없으면 DB 관리자가 extension을 먼저 생성해야 Alembic migration이
성공한다. GPU device나 driver library가 외부 컨테이너에 전달되지 않은 경우에는
로컬 vLLM/embedding을 시작할 수 없으므로 두 endpoint를 외부로 구성한다.

## 3. 주요 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MININBLM_DB_PORT` | `5433` | host network에서 PostgreSQL이 bind할 loopback 포트 |
| `NATIVE_MANAGE_DB` | `true` | 비컨테이너 실행에서 로컬 PostgreSQL을 직접 관리할지 여부 |
| `NATIVE_START_EMBEDDING` | `true` | 비컨테이너 실행에서 BGE-M3 process를 시작할지 여부 |
| `NATIVE_START_LLM` | `true` | 비컨테이너 실행에서 vLLM process를 시작할지 여부 |
| `NATIVE_DB_OS_USER` | `postgres` | root container에서 PostgreSQL process 권한을 내릴 OS 사용자 |
| `NATIVE_DB_DATA_DIR` | `./.native/postgres` | 로컬 PostgreSQL data directory |
| `NATIVE_UPLOAD_DIR` | `./.native/uploads` | 비컨테이너 API의 업로드 PDF 저장 경로 |
| `NATIVE_ENV_DIR` | `.venv-native` | API와 embedding Python 환경 |
| `NATIVE_VLLM_ENV_DIR` | `.venv-vllm` | 충돌을 분리한 vLLM Python 환경 |
| `NATIVE_VLLM_VERSION` | `0.25.0` | native 설치와 호환 patch의 기준 vLLM version |
| `VLLM_MODEL_PATH` | `./google/gemma-4-12B-it-W4A16` | 호스트의 양자화 모델 경로 |
| `MODEL_HF_REPO_ID` | 없음 | 원샷 컨테이너가 최초 기동 시 받을 공개 Hugging Face `owner/repository` |
| `MODEL_HF_REVISION` | 없음 | Hugging Face 모델을 고정하는 필수 40자리 commit SHA |
| `MODEL_ARCHIVE_URL` | 없음 | 원샷 컨테이너가 최초 기동 시 받을 모델 archive 직접 URL |
| `MODEL_ARCHIVE_SHA256` | 없음 | 모델 archive의 필수 SHA-256 checksum |
| `MODEL_KEEP_ARCHIVE` | `false` | 설치 성공 후 다운로드 archive를 `/data/model-cache`에 유지할지 여부 |
| `VLLM_MAX_MODEL_LEN` | `16384` | 12B·31B 공통 최대 sequence length |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.65` | 12B vLLM GPU 메모리 목표 |
| `VLLM_MAX_NUM_SEQS` | `4` | vLLM scheduler가 동시에 처리할 최대 활성 sequence 수 |
| `LLM_ENDPOINTS_FILE` | `config/llm-endpoints.json` | OpenAI 호환 endpoint 허용 목록 JSON 경로 |
| `MAX_UPLOAD_BYTES` | `52428800` | 서버가 허용하는 PDF 파일 최대 바이트 수 |
| `MAX_REQUEST_BODY_BYTES` | `53477376` | 50MiB PDF와 multipart overhead를 허용하는 전체 HTTP request body 상한 |
| `READINESS_TIMEOUT_SECONDS` | `3` | readiness 구성요소별 최대 점검 시간(초) |
| `LOG_LEVEL` | `INFO` | API JSON 구조화 로그 수준 |
| 활성 retrieval preset | `balanced` | DB에서 관리하며 기본 `top_k=8`, 청크 `1000/150` |
| `AUTH_SESSION_TTL_HOURS` | `168` | 로그인 세션 유지 시간 |
| `AUTH_COOKIE_SECURE` | `false` | HTTPS 운영 환경에서는 `true`로 설정 |
| `BOOTSTRAP_ADMIN_USERNAME` | 없음 | 최초 관리자 생성 시에만 설정할 사용자명 |
| `BOOTSTRAP_ADMIN_PASSWORD` | 없음 | 최초 로그인에서 교체할 안전한 임시 비밀번호 |

`VLLM_MAX_MODEL_LEN=16384`는 Docker, native, all-in-one 12B·31B의 공통 기본값입니다.
Vast.ai Template이나 다른 orchestrator가 같은 환경변수를 지정하면 image 기본값보다
우선하므로 외부 배포 설정도 `16384`로 맞춰야 합니다.

Bootstrap 관리자 변수는 둘 다 설정하거나 둘 다 비워야 합니다. 비밀번호는 12자
이상이며 영문 대·소문자, 숫자, 기호 중 3종 이상이어야 하고 사용자명을 포함할 수
없습니다. 계정 생성 후에는 두 변수를 제거해도 됩니다.

언어모델 등록정보는 `LLM_ENDPOINTS_FILE`이 가리키는 JSON 파일에서 수동 관리합니다.
최상위 `default_endpoint`와 `endpoints` 배열이 필요하며 각 endpoint는 `key`,
`display_name`, `base_url`, `model`, `supports_vision`을 포함합니다. 인증값은
`api_key`와 `api_key_env` 중 정확히 하나를 사용합니다. 실제 secret은 JSON에
기록하지 않고 환경변수를 참조하는 `api_key_env`를 권장합니다.

| 필드 | 값의 의미 | 권장 사용처 |
|---|---|---|
| `api_key` | HTTP 인증에 사용할 값 자체 | 인증 없는 vLLM의 `"EMPTY"` placeholder |
| `api_key_env` | 실제 인증값이 들어 있는 환경변수 이름 | 상용 API와 인증이 설정된 외부 vLLM |

두 필드는 최종적으로 같은 `Authorization: Bearer ...` 인증값을 만들지만 secret의
저장 위치가 다릅니다. `api_key`에 실제 secret을 기록하면 JSON·백업·Git 이력에
평문이 남을 수 있으므로 사용하지 않습니다. 인증 없는 로컬 또는 외부 vLLM은
OpenAI client가 요구하는 placeholder로 `"api_key": "EMPTY"`를 사용합니다.

```json
{
  "key": "external-vllm",
  "display_name": "External vLLM",
  "base_url": "http://192.168.0.100:8000/v1",
  "api_key": "EMPTY",
  "model": "served-model-name",
  "supports_vision": false
}
```

상용 API나 `vllm serve --api-key ...`로 보호한 endpoint는 실제 값을 환경변수에
두고 JSON에서는 그 환경변수 이름만 참조합니다.

```json
{
  "default_endpoint": "remote",
  "endpoints": [
    {
      "key": "remote",
      "display_name": "Remote LLM",
      "base_url": "https://llm.example/v1",
      "api_key_env": "REMOTE_LLM_API_KEY",
      "model": "model-name",
      "supports_vision": false
    }
  ]
}
```

JSON은 API 시작 시 전체 검증되며 파일 오류, 중복 key, 존재하지 않는 기본 endpoint,
누락된 secret 환경변수가 있으면 시작을 거부합니다. 변경 후 API를 재시작해야 합니다.
개별 Docker Compose는 `config/llm-endpoints.json`을 read-only mount하고, native는
`.env`의 `LLM_ENDPOINTS_FILE`을 사용합니다. all-in-one Compose는
`MININBLM_LLM_CONFIG_FILE`의 호스트 파일을 `/data/config/llm-endpoints.json`으로
mount합니다. 이미지를 Compose 없이 처음 실행하면 내장 variant 기본값을 해당
`/data` 경로에 생성합니다.

배열에 서로 다른 주소의 endpoint를 여러 개 등록하면 로그인한 각 사용자가 작업공간
상단에서 자신의 활성 endpoint를 선택합니다. 사용자별 선택값은 DB에 보존되고 전환
시 `/models` 응답의 model ID를 확인합니다. Vision caption을 활성화할 때는 선택한
endpoint의 `supports_vision`이 `true`여야 합니다.

`embedding`과 `llm`은 같은 GPU를 사용할 수 있습니다.
`VLLM_GPU_MEMORY_UTILIZATION`은 vLLM 프로세스별 전체 GPU 용량 목표치이며, 모델
weight, 실행 workspace, CUDA context와 KV cache가 함께 VRAM을 사용합니다. 한
vLLM 인스턴스의 여러 요청은 이 메모리 풀을 공유하므로 `VLLM_MAX_NUM_SEQS`배의
VRAM을 예약하지 않습니다. 반대로 같은 GPU에서 vLLM 인스턴스를 여러 개 실행하면
각 인스턴스의 비율이 중첩되므로 합계와 embedding 등 외부 GPU 사용량을 함께
제한해야 합니다.

12B RTX 3090 profile은 `VLLM_GPU_MEMORY_UTILIZATION=0.65`,
`VLLM_MAX_NUM_SEQS=4`를 사용합니다. 31B H200 profile은 각각 `0.70`, `8`을
사용하며 `VLLM_TENSOR_PARALLEL_SIZE=1`입니다. 31B 조합은 이번 변경에서 실행
검증하지 않았습니다.

`5433`을 다른 PostgreSQL이 사용 중이면 `.env`에서 `MININBLM_DB_PORT`를 변경한다.
Compose는 API 연결 주소에도 같은 포트를 적용한다. 비컨테이너 실행은
`DATABASE_URL`의 포트도 함께 변경해야 한다.

## 4. API 계약

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/health` | API process 상태 |
| `GET` | `/health/ready` | DB, embedding, vLLM 통합 준비 상태 |
| `GET` | `/metrics` | Prometheus 형식 API·검색·LLM 지표 |
| `POST` | `/auth/register` | 공개 회원가입과 로그인 세션 발급 |
| `POST` | `/auth/login` | 로그인 세션 발급 |
| `POST` | `/auth/logout` | 현재 로그인 세션 폐기 |
| `POST` | `/auth/password` | 현재 비밀번호 검증 후 새 비밀번호 설정 |
| `DELETE` | `/auth/account` | 비밀번호·사용자명 재확인 후 계정과 소유 데이터 삭제 |
| `GET` | `/auth/me` | 현재 로그인 사용자 |
| `POST` | `/admin/users/password-reset` | 임시 비밀번호 설정, 기존 세션 폐기와 다음 로그인 변경 강제 |
| `POST` | `/documents` | multipart PDF 업로드 |
| `GET` | `/documents` | 문서 목록 |
| `GET` | `/documents/{id}` | 문서와 인덱싱 상태 |
| `GET` | `/documents/{id}/file` | 브라우저에서 여는 원본 PDF |
| `DELETE` | `/documents/{id}` | 문서, page/chunk와 원본 파일 삭제 |
| `POST` | `/chat` | 현재 사용자의 전체 indexed 문서 기반 질문 |
| `POST` | `/chat/stream` | 동일한 질문을 SSE 답변 스트림으로 처리 |
| `GET` | `/admin/retrieval` | 프리셋 목록, 활성 설정과 최근 작업 조회 |
| `GET` | `/admin/retrieval/traces` | 최근 답변의 단계별 retrieval trace 조회 |
| `POST` | `/admin/retrieval/presets/{key}/activate` | 프리셋 변경 작업 시작 |
| `POST` | `/admin/retrieval/algorithms/{key}/activate` | 검색 알고리즘 즉시 변경 |
| `GET` | `/language-models` | 로그인 사용자의 등록 언어모델과 선택 조회 |
| `POST` | `/language-models/{key}/activate` | endpoint 검증 후 사용자별 언어모델 전환 |
| `GET` | `/admin/retrieval/jobs/{id}` | 재인덱싱 작업 상태 조회 |
| `POST` | `/admin/retrieval/jobs/{id}/retry` | 실패한 재인덱싱 작업 재시도 |

`/health`는 외부 의존성과 무관한 API liveness다. `/health/ready`는 DB
`SELECT 1`, embedding `/health`, vLLM `/v1/models`를 병렬 확인한다. 모든
구성요소가 정상일 때 HTTP 200과 `ready`, 하나라도 실패하면 HTTP 503과
`not_ready`를 반환한다. 구성요소별 `status`, `latency_ms`, 안전하게 정규화한
`detail`을 포함하며 내부 URL이나 DB 접속 문자열은 노출하지 않는다.

`/documents`와 `/chat` 경로는 로그인이 필요합니다. 세션 토큰은 `HttpOnly`,
`SameSite=Lax` 쿠키로 전달되며 DB에는 토큰 원문 대신 SHA-256 해시만
저장됩니다. 사용자는 자신이 소유한 문서와 대화에만 접근할 수 있고, 문서 조회·
원본 열람·삭제에서 다른 사용자의 문서 ID를 요청하면 HTTP 404를 반환합니다.
`/chat` 검색 쿼리는 `documents.owner_id`를 현재 사용자 ID로 제한합니다.

### 관리자 지정과 검색 프리셋

공개 회원가입 계정은 기본적으로 `user` 역할이며 기본 관리자 계정은 없습니다.
`BOOTSTRAP_ADMIN_USERNAME`과 `BOOTSTRAP_ADMIN_PASSWORD`를 명시하면 존재하지
않는 계정을 최초 관리자로 생성합니다. 기존 관리자 비밀번호는 API 재시작 시
환경변수 값으로 덮어쓰지 않습니다. Bootstrap 관리자와 CLI로 승격한 관리자는
최초 로그인 후 비밀번호를 변경할 때까지 인증 조회와 비밀번호 변경 외 API에
HTTP 403으로 차단됩니다. 변경 시 현재 세션을 제외한 기존 로그인 세션도
폐기됩니다.

일반 사용자는 작업공간의 `계정` 화면에서 비밀번호를 변경할 수 있습니다. 변경하면
현재 브라우저 세션만 유지되고 다른 로그인 세션은 모두 폐기됩니다. 회원탈퇴는
현재 비밀번호와 사용자명 재입력을 요구하며 다음 데이터를 hard delete합니다.

- 인증 세션
- 업로드 문서, page, chunk와 embedding
- 작업공간 대화와 메시지
- `data/uploads/documents/{id}`의 원본 PDF

과거 재인덱싱 작업은 감사 이력으로 보존하되 삭제된 요청자 ID를 `NULL`로
전환합니다. `uploaded` 또는 `processing` 문서가 있거나 전역 재인덱싱이 진행
중이면 동시 작업 충돌을 피하기 위해 회원탈퇴를 거절합니다.

기존 계정을 추가 관리자로 지정하거나 권한을 회수할 때는 다음 CLI를 사용합니다.

```bash
docker compose exec api python -m app.cli.set_admin <username>
docker compose exec api python -m app.cli.set_admin --revoke <username>

# 비컨테이너 실행
.venv-native/bin/python -m app.cli.set_admin <username>
.venv-native/bin/python -m app.cli.set_admin --revoke <username>
```

관리자 API는 `admin` 역할만 접근할 수 있습니다. 프리셋의 청크 크기 또는
오버랩이 바뀌면 모든 문서를 다시 청킹·임베딩하며, 완료 후 새 프리셋과 index
version을 활성화합니다. 작업 중에는 문서 업로드·삭제와 질문을 HTTP 503으로
차단하지만 문서 목록과 상태 조회는 허용합니다. 사용자, 세션, 원본 PDF는
보존됩니다. 문서에 직접 연결된 기존 대화는 재인덱싱 시 삭제되지만, 작업공간
대화는 특정 문서에 귀속되지 않습니다. 재인덱싱 후에도 대화와 문서/page source
표시는 유지되며, 삭제된 문서의 과거 source는 열 수 없는 상태로 반환됩니다.
API가 작업 중 재시작되면 `pending` 또는 `running` 작업을 감지해 진행률을
초기화하고 모든 문서를 처음부터 다시 처리합니다.

API 시작 시 전역 재인덱싱 작업이 없다면 `uploaded` 또는 `processing` 상태의
개별 문서도 자동 복구합니다. 원본 PDF가 존재하는 문서는 기존 page, chunk와
관련 대화를 정리한 뒤 활성 preset으로 처음부터 다시 인덱싱합니다. 업로드 도중
중단되어 원본 파일이 없는 문서는 복구할 수 없으므로 원인을 기록하고 `failed`
상태로 전환합니다. 전역 재인덱싱이 복구 중이면 개별 worker는 시작하지 않고
재인덱싱 작업이 모든 문서를 처리합니다.

검색 알고리즘은 청킹 preset과 독립적으로 선택합니다. `dense`는 BGE-M3와
pgvector cosine 검색, `keyword`는 PostgreSQL FTS, `substring`은 pg_trgm,
`hybrid`는 세 결과의 Reciprocal Rank Fusion을 사용합니다. Dense와 Hybrid 후보는
BGE-M3 cosine으로 재정렬합니다. 관련성 점수는 원질문 70%와 goal 검색어 최대값
30%를 결합하고, 최종 점수는 관련성 80%와 기존 검색 순위 20%를 사용합니다.
goal별 최상위 후보를 하나 이상 보존하며 BGE-M3 호출 실패 시 기존 검색 순위를
유지합니다. FTS와 trigram 인덱스는 상시 유지하므로 검색 알고리즘 변경에는 문서
재인덱싱이 필요하지 않습니다.

`uploaded` 또는 `processing` 상태의 문서는 background indexing과 충돌하지
않도록 삭제 요청에 HTTP 409를 반환합니다. `indexed`와 `failed` 문서를
삭제하면 관련 pages, chunks, 해당 문서에 직접 연결된 기존 chat session과 원본
파일 디렉터리를 함께 제거합니다. 작업공간 chat session은 유지됩니다.

PDF 업로드는 `.pdf` 파일명과 PDF MIME type을 모두 요구합니다.
`MAX_REQUEST_BODY_BYTES`를 넘는 전체 HTTP body는 form parsing 전에 HTTP 413으로
거절합니다. `MAX_UPLOAD_BYTES`를 넘는 PDF도 저장 중 HTTP 413을 반환합니다. 기본
request 상한은 51MiB이므로 50MiB PDF와 multipart overhead를 함께 허용합니다.
`%PDF-` 시그니처가 없거나 PyMuPDF가 열 수 없는 손상 파일 또는 암호화된 파일은
HTTP 400을 반환합니다. 거절된 업로드의 문서 DB 행과 부분 저장 파일은 즉시
정리됩니다. 텍스트가 없는 정상 PDF는 업로드 자체는 허용하지만 인덱싱 단계에서
`failed`로 전환됩니다.

`POST /chat` 요청과 응답의 최소 형태는 다음과 같습니다.

```json
{
  "question": "업로드한 자료의 핵심 내용을 설명해 주세요."
}
```

```json
{
  "session": {
    "session_id": 12,
    "title": "업로드한 자료의 핵심 내용을 설명해 주세요.",
    "created_at": "2026-08-05T10:00:00Z",
    "updated_at": "2026-08-05T10:00:00Z"
  },
  "answer": "답변 내용",
  "sources": [
    {
      "document_id": 1,
      "document_title": "프로젝트_가이드.pdf",
      "page": 1,
      "chunk_id": 1,
      "available": true
    }
  ]
}
```

첫 질문은 `session_id`를 생략하며, 응답의 `session.session_id`를 후속 요청에
보내면 같은 대화에 메시지가 추가된다.

```json
{
  "session_id": 12,
  "question": "앞에서 설명한 내용의 예시도 알려주세요."
}
```

세션 API:

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/chat/sessions` | 최근 활동순 대화 목록 |
| `GET` | `/chat/sessions/{id}` | 메시지와 source 복원, `limit`/`before_id` 페이지 조회 |
| `DELETE` | `/chat/sessions/{id}` | 현재 사용자 소유 대화 삭제 |

후속 질문 생성에는 같은 세션의 최근 8개 메시지를 최대 8,000자까지 포함한다.
삭제된 PDF를 참조하는 과거 source는 문서명을 보존하지만 `available=false`로
반환되어 원본 열기를 차단한다.
LLM이 `[[NO_SOURCE]]`로 자료 부재를 표시하면 API는 마커를 사용자 답변에서
제거하고 빈 `sources` 배열을 반환한다. `[[NO_SOURCE]`처럼 닫는 대괄호를 일부
누락해도 동일하게 처리한다.

검색된 top-k chunk는 LLM에 제공하는 후보일 뿐 사용자에게 그대로 노출하지
않는다. 근거 답변은 끝에 `[Source 1, Page 3; Source 2, Page 5]` 형식으로 실제
참고한 Context 번호를 표시한다. API는 유효한 `Source N`만 해당 chunk의 문서와
페이지로 변환하며, 같은 문서·페이지의 중복 chunk는 하나로 합친다. 범위를 벗어난
번호와 답변에서 인용되지 않은 검색 후보는 `sources`에 포함하지 않는다.
이 규칙 도입 전에 저장된 대화도 조회 시 답변의 `Source N`과 기존 후보 순서를
대조해 필터링하므로 DB를 다시 인덱싱하지 않아도 된다.

질문은 독립형 질의와 최대 3개의 세부 검색 질의로 분해할 수 있다. 다중 질의
결과는 RRF로 합치고 인접 chunk와 의미 재정렬 후보를 보강한다. 그 뒤 LLM이
원질문에 필요한 근거의 충족도를 판정한다. 근거가 부족하면 누락 전제에 맞춘
표적 chunk 검색과 page FTS·trigram 계층 fallback을 최대 2회 예산 안에서
수행한다. 페이지 fallback은 세부 질의별 상위 페이지를 보존한 뒤 해당 페이지와
겹치는 기존 chunk만 BGE-M3로 재정렬한다. 재검색이 비어도 기존 Context는
유지하며, 최종 판정이 여전히 부족하거나 형식이 불안정하면 병합 근거를 답변
모델에 전달한다. 최종 답변 여부는 범용 RAG system prompt의 엄격한
`NO_SOURCE` 규칙이 결정한다.

`POST /chat/stream`은 요청 형식과 세션 규칙이 `/chat`과 같고 다음 SSE event를
순서대로 보낸다.

| Event | Data | 설명 |
|---|---|---|
| `session` | 세션 요약 | 새 세션 또는 요청한 세션 식별 |
| `delta` | `{"text":"..."}` | 화면에 즉시 추가할 답변 조각 |
| `revision` | `{"text":"..."}` | 인용 검증으로 보정된 최종 답변 전체 교체 |
| `sources` | source 배열 | 근거가 있는 답변의 출처, 자료 부재 시 빈 배열 |
| `done` | 세션 요약 포함 객체 | 답변과 대화 이력 저장 완료 |
| `error` | 안전한 오류와 request ID | 스트림 처리 실패, `done`은 전송하지 않음 |

완료된 스트림만 사용자 질문과 답변을 DB에 저장한다. 새 세션에서 생성 또는
전송이 실패하면 빈 세션도 정리한다. 초기 출력은 `NO_SOURCE` 판정이 끝날 때까지
짧게 버퍼링하므로 자료 부재 마커가 브라우저에 노출되지 않는다.
실질 문장에 인용이 없거나 Source/Page가 검색 Context와 맞지 않으면 인용 보정
LLM을 한 번 호출한다. 스트리밍 중 보정이 발생하면 기존 delta를 유지하면서
`revision`으로 화면을 교체하고, 보정된 답변만 대화 이력에 저장한다.

## 5. 상태 확인

```bash
curl -sS http://localhost:8080/health
curl -sS http://localhost:8080/health/ready
curl -sS http://localhost:8080/metrics
curl -sS http://localhost:8070/health
curl -sS http://localhost:8010/v1/models
curl -sS -c session.cookie \
  -H 'Content-Type: application/json' \
  -d '{"username":"student01","password":"change-this-password"}' \
  http://localhost:8080/auth/register
curl -sS -b session.cookie http://localhost:8080/documents
curl -sS -b session.cookie -D - -o /dev/null http://localhost:8080/documents/1/file
curl -sS -b admin.cookie 'http://localhost:8080/admin/retrieval/traces?limit=20'
```

모든 API 응답은 `X-Request-ID`를 반환한다. 클라이언트가 영문·숫자와 `._-`로
구성된 128자 이하 값을 보내면 그대로 사용하고, 아니면 서버가 새 값을 만든다.
로그는 stdout에 JSON 한 줄씩 기록되며 request ID, method, route, status와
전체 응답 시간(`duration_ms`)을 포함한다. 스트리밍 요청의 시간은 마지막 SSE
event 전송까지 측정한다.

각 완료 답변은 assistant 메시지 metadata에 schema version 1 retrieval trace를
저장한다. trace에는 request ID, 검색 계획, 단계별 문서·페이지·chunk ID·점수,
근거 충족도와 재검색어, 최종 `grounded`/`no_context`/`no_source`/
`uncited_answer` 상태와 지연이 포함된다. chunk 본문과 답변 본문은 중복 저장하지
않는다. 관리자만 `GET /admin/retrieval/traces`로 최신순 조회할 수 있으며 대화가
삭제되면 해당 trace도 함께 삭제된다. 같은 trace는 JSON 구조화 로그에도 기록된다.

`/metrics`에는 다음 애플리케이션 지표가 포함된다.

- `mininblm_http_requests_total`, `mininblm_http_request_duration_seconds`
- `mininblm_retrieval_requests_total`, `mininblm_retrieval_duration_seconds`
- `mininblm_rerank_requests_total`, `mininblm_rerank_duration_seconds`
- `mininblm_evidence_coverage_requests_total`, `mininblm_evidence_coverage_duration_seconds`
- `mininblm_retrieval_retries_total`
- `mininblm_citation_validation_requests_total`, `mininblm_citation_validation_duration_seconds`
- `mininblm_llm_requests_total`, `mininblm_llm_duration_seconds`
- `mininblm_llm_time_to_first_token_seconds`, `mininblm_chat_streams_total`

운영에서는 `/metrics`를 모니터링망에서만 접근하도록 reverse proxy에서 제한한다.
`/chat/stream` 앞에 Nginx 등을 둘 경우 응답 버퍼링을 끄고 idle timeout을 LLM
최대 생성 시간보다 길게 설정한다. API도 `X-Accel-Buffering: no`를 반환한다.

정상적인 PDF 응답에는 다음 header가 포함됩니다.

```text
content-type: application/pdf
content-disposition: inline; filename="...pdf"
```

## 6. GPU 및 vLLM 문제 해결

### `UVA is not available`

WSL2의 기본 pinned memory 비활성화와 vLLM Model Runner V2의 UVA 요구가 충돌할 때 발생합니다. Compose에는 다음 설정이 반영되어 있습니다.

```text
VLLM_WSL2_ENABLE_PIN_MEMORY=1
ipc: host
```

GPU가 컨테이너에 전달되는지도 확인합니다.

```bash
docker compose exec llm nvidia-smi
```

### 시작 시 목표 VRAM 부족

다음 형태의 오류는 시작 시 free VRAM보다 목표 사용량이 클 때 발생합니다.

```text
Free memory ... is less than desired GPU memory utilization
```

다른 GPU 프로세스를 종료하거나 `.env`의 `VLLM_GPU_MEMORY_UTILIZATION`을
낮춥니다. 12B RTX 3090 profile 기본값은 `0.65`, 31B H200 환경 예시는
`0.70`입니다.

### KV cache 부족

다음 형태의 오류는 설정한 최대 sequence length를 수용할 KV cache가 없다는 뜻입니다.

```text
KV cache is needed, which is larger than the available KV cache memory
```

`VLLM_MAX_MODEL_LEN` 또는 `VLLM_MAX_NUM_SEQS`를 낮춥니다. 여유 VRAM이 있고
같은 GPU의 다른 프로세스 예산과 충돌하지 않는다면
`VLLM_GPU_MEMORY_UTILIZATION`을 높일 수 있습니다. preemption/recompute가
발생하면 활성 sequence 상한부터 낮춥니다.

### Gemma 4 W4A16 적재 오류

`Dockerfile.llm`은 Gemma 4 unified 모델의 compressed-tensors quantization 연결을 보완하는 로컬 vLLM patch를 적용합니다. 모델 구조 또는 vLLM base image가 바뀌면 patch 적용과 실제 completion 요청을 다시 검증해야 합니다.

## 7. 데이터 보존

- 원본 PDF: 호스트 `./data`, 컨테이너 `/app/data`
- PostgreSQL: Docker volume `postgres_data`
- Hugging Face cache: Docker volume `hf_cache`
- 양자화 모델: 호스트 `VLLM_MODEL_PATH`, 컨테이너에 read-only mount

`docker compose down`은 위 데이터를 삭제하지 않습니다. `down -v`는 DB와 cache volume을 제거하므로 데이터 삭제 의도가 있을 때만 사용합니다.

### 백업과 복원

`backup.sh`는 API를 잠시 정지하고 PostgreSQL custom dump와 업로드 PDF를 동일
시점에 수집한다. Docker 기본 경로는 `data/uploads`, native 기본 경로는
`.native/uploads`이며, 기본 출력은 Git에서 제외되는 `./backups`이다.

```bash
./backup.sh
# 비컨테이너 PostgreSQL/API
RUNTIME_MODE=native ./backup.sh
```

bundle에는 다음 파일이 포함됩니다.

- `database.dump`
- `uploads.tar.gz`
- 생성 시각과 Git commit을 기록한 `manifest.txt`
- 세 파일의 SHA-256을 기록한 `SHA256SUMS`

먼저 데이터를 변경하지 않는 검증 모드를 실행합니다.

```bash
# 검증 모드는 실행 중인 DB와 runtime 종류에 무관하다.
./restore.sh --verify-only backups/mininblm-backup-<timestamp>.tar.gz
```

실제 복원은 DB와 업로드 PDF를 교체하므로 서비스 점검 시간에 실행합니다.
스크립트는 API를 정지하고 현재 DB·uploads rollback snapshot을 만든 후 복원하며,
실패하면 직전 상태를 되돌리고 API를 다시 시작합니다.

```bash
./restore.sh --yes backups/mininblm-backup-<timestamp>.tar.gz
# 비컨테이너 PostgreSQL/API
RUNTIME_MODE=native ./restore.sh --yes backups/mininblm-backup-<timestamp>.tar.gz
```

운영 배포 전에는 운영 복사본 또는 격리 환경에서 `--yes` 복원 리허설과 문서 원본
열기까지 확인해야 합니다. `down -v` 실행 전에는 반드시 별도 저장장치로 bundle을
복사합니다.

## 8. 현재 제한사항

- 이메일 확인, 비밀번호 재설정, 계정 잠금과 가입 rate limit이 없습니다.
- HTTP로 실행하는 로컬/LAN 기본 설정에서는 `AUTH_COOKIE_SECURE=false`입니다. 외부 운영 환경은 HTTPS와 `true` 설정이 필요합니다.
- 대화 생성 문맥은 최근 8개 메시지, 최대 8,000자로 제한됩니다. 검색 계획은 직전
  사용자 질문 최대 500자와 직전 답변 최대 1,000자를 참고해 독립형 질문과 최대
  4개의 검색 질의를 만듭니다. 계획 실패 시 원문 질문 하나로 검색합니다.
- 모든 질문은 검색 계획용 LLM 호출이 1회 추가됩니다. Dense와 Hybrid는 최대
  `top_k × 3` 후보를 원 질문과 goal 검색어로 BGE-M3 재정렬합니다. 원질문
  embedding 70%와 goal 검색어 최대값 30%를 결합하며 goal별 최상위 후보를
  보존합니다. BGE-M3 호출 실패 시 기존 검색 순위로 fallback합니다.
- 검색 결과가 있으면 근거 충족도 LLM 호출이 1회 추가됩니다. 부족 판정이
  계속되면 표적 chunk 검색과 page 계층 fallback을 합쳐 최대 2회 재시도하고 각
  결과를 다시 판정하므로 충족도 호출은 최대 3회입니다. page fallback은 최대
  12개 페이지와 16개 chunk로 제한합니다. 최종 판정은 검색 제어와 관측 목적으로
  사용하며 답변 가능 여부는 RAG 답변 모델이 다시 판단합니다.
- 답변의 실질 문장마다 유효한 Source/Page가 이미 있으면 인용 검증 호출을
  생략합니다. 인용 누락이나 잘못된 번호·페이지가 감지된 경우에만 보정 LLM을
  최대 1회 호출하며, 실패하거나 유효한 인용을 만들지 못하면 원 답변을 유지하고
  유효한 Source/Page만 출처 목록에 포함합니다.
- 질문은 로그인 사용자의 모든 `indexed` 문서를 검색하며, 처리 중이거나 실패한
  문서는 검색 대상에서 제외됩니다.
- 문서 처리는 API process의 `BackgroundTasks`를 사용하며 재시작 시 처음부터 복구하지만 별도 worker/queue가 없어 API process 수명과 자원을 공유합니다.
- 프리셋 재인덱싱은 DB 작업 상태를 이용해 API 재시작 시 처음부터 복구하지만 별도 worker/queue가 없어 API process 수명과 자원을 공유합니다.
- 텍스트 기반 PDF만 처리하며 scanned PDF용 OCR은 없습니다.
- Prometheus 수집 서버와 대시보드·경보 규칙은 배포 구성에 포함되지 않습니다.

## 9. 완료된 검증

- 네 컨테이너 동시 실행
- uv `common`/`api`/`embedding`/`dev` dependency group 분리
- API 이미지에서 Torch, Sentence Transformers, Transformers 및 CUDA wheel 제거
- API 이미지 크기 `6,555,721,208` bytes에서 `206,676,250` bytes로 감소
- embedding 이미지의 Torch/Sentence Transformers 및 GPU embedding 구동 유지
- BGE-M3 health 및 embedding 생성
- Gemma 4 12B W4A16 vLLM 모델 적재와 completion
- PDF 업로드, text 추출, chunk embedding과 pgvector 저장
- 실제 RAG 질문, 답변 및 page source 반환
- PDF `inline` 원문 endpoint
- 데스크톱과 모바일 Web UI 렌더링
- 모바일 문서 drawer, 질문 전송, 출처 선택과 PDF frame 열기
- Argon2id 비밀번호 해시, 회원가입·로그인·로그아웃과 세션 폐기
- 기본 관리자 제거, 명시적 bootstrap과 최초 로그인 비밀번호 변경 강제
- 일반 사용자 비밀번호 변경, 다른 세션 폐기와 회원탈퇴 데이터 정리
- DB·uploads 백업 bundle 생성, SHA-256 검증과 API 자동 재시작
- 서로 다른 두 사용자 간 문서 목록·원본 PDF·질의·삭제 접근 격리
- 데스크톱·모바일 인증 UI와 모바일 가로 overflow 없음
- 관리자 권한 격리, 프리셋 5개 조회·전환·진행 상태 UI
- 실제 PDF의 프리셋 변경 재청킹, 대화 정리와 index version 갱신
- 재인덱싱 유지보수 모드와 문서 질문/삭제 동시성 제어
- API 재시작 후 중단된 재인덱싱 작업의 자동 복구
- API 재시작 후 `uploaded/processing` PDF의 자동 재인덱싱과 누락 원본 실패 처리
- Dense, FTS Keyword, pg_trgm Substring과 RRF Hybrid 검색 결과
- 다중 질의 RRF, 인접 청크 확장과 goal별 후보를 보존하는 BGE-M3 재정렬
- 복합 질의 근거 충족도 판정, 표적·페이지 계층 재검색 최대 2회와 Context 보존
- 사용자별 page FTS·trigram 범위 탐색, 질의별 page anchor와 BGE-M3 chunk 재정렬
- 답변별 retrieval trace metadata, 구조화 로그와 관리자 조회 API
- 주장별 Source/Page 검증과 동기·SSE 인용 보정 및 저장 일치
- 관리자 UI의 청킹 preset·검색 알고리즘 독립 전환과 모바일 overflow 없음
- 서버의 업로드 크기, 확장자, MIME, PDF 시그니처·구조·암호화 검증
- DB, embedding, vLLM 통합 readiness와 API Docker healthcheck
- SSE 답변 delta·source·완료 event와 완료 시 대화 저장
- JSON 구조화 로그, request ID 전파와 Prometheus HTTP·검색·LLM 지표

## 10. 자동화 테스트

전체 테스트는 프로젝트 루트에서 실행합니다.

```bash
./scripts/test.sh -q
```

`scripts/test.sh`는 다음 순서로 동작합니다.

1. 기존 `mininblm-test` Compose project를 정리합니다.
2. tmpfs 기반 PostgreSQL 17/pgvector 컨테이너를 host port `55432`에서 시작합니다.
3. 테스트 DB에 Alembic migration 전체를 적용합니다.
4. 단위 테스트와 API·DB 통합 테스트를 실행합니다.
5. 성공 또는 실패 여부와 관계없이 테스트 컨테이너를 종료합니다.

테스트 DB의 이름과 계정은 운영 설정과 다르며 운영 DB port `5433`,
`postgres_data`, `data/` 업로드 파일을 사용하지 않습니다. embedding과 LLM
클라이언트는 테스트 대역으로 교체하므로 GPU 서비스도 필요하지 않습니다.

현재 자동화 범위는 프리셋 유효성·변경 영향, 인증 입력, 관리자 bootstrap·강제
비밀번호 변경·다중 세션 폐기, RRF 병합, 회원가입과 세션, 사용자별 문서 격리,
PDF 업로드·삭제 제약, 대화 저장·복원·소유권·페이지 조회, SSE 스트리밍,
request ID·metric, 관리자 권한과
프리셋 전환, 네 검색 알고리즘의 실제 PostgreSQL 질의, 문서 및 재인덱싱 복구,
비밀번호 변경과 회원탈퇴 데이터 정리를
포함합니다. 실제 PDF 파싱·embedding·LLM 생성과 브라우저 레이아웃은 별도의
서비스 및 UI smoke 검증 범위입니다.

단위 테스트만 실행하려면 테스트 DB 없이 다음 명령을 사용합니다.

```bash
uv run pytest tests/unit -q
```

### 실제 모델 E2E

운영 네 서비스가 정상 실행 중일 때 실제 embedding과 vLLM을 포함한 smoke
테스트를 실행합니다.

```bash
./scripts/e2e.sh -q
```

E2E Compose project는 운영 `embedding`과 `llm` endpoint만 공유합니다. pytest는
전용 API 컨테이너 내부에서 실행되어 WSL과 Docker 사이의 host-network port
전달에 의존하지 않습니다. API, PostgreSQL, 관리자 계정, 업로드 경로는 다음과
같이 격리되고 테스트 종료 시 자동 삭제됩니다.

| 자원 | E2E 값 |
|---|---|
| API | `127.0.0.1:18080` |
| PostgreSQL | `127.0.0.1:55433`, tmpfs |
| DB 이름 | `rag_e2e_db` |
| PDF fixture | `sample_fall_prevention.pdf` |

검증 범위는 실제 PDF 4페이지 파싱, BGE-M3 1024차원 임베딩 저장, 실제 SSE
delta와 완료 event, 고유 정답과 page 1 출처 검색, 자료에 없는 질문 제한,
스트리밍·검색·LLM metric과 테스트 문서 삭제입니다. 생성 모델 결과는 문장
전체가 아니라 필수 용어와 출처 page로 판정합니다.

### Retrieval 품질 benchmark

LLM 생성과 분리해 검색 품질과 지연만 비교할 때 실행합니다.

```bash
./scripts/benchmark-retrieval.sh
```

`docker-compose.benchmark.yml`은 tmpfs PostgreSQL과 API dependency 기반 runner를
같은 Docker network에서 실행한다. 운영 embedding만 공유하며 운영 DB, 업로드
파일과 LLM은 사용하지 않는다. 12페이지 평가 corpus를 5개 preset으로 각각
재인덱싱하고 4개 알고리즘의 Recall@5, Hit rate@5, MRR@5, p50/p95 retrieval
지연과 indexing 시간을 JSON/Markdown으로 저장한다. 자세한 fixture와 옵션은
`docs/retrieval-evaluation.md`를 참조한다.
