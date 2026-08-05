# 운영 및 검증 가이드

## 1. 서비스와 포트

| 서비스 | 호스트 포트 | 역할 | GPU |
|---|---:|---|---|
| `api` | 8080 | FastAPI, Web UI, 문서 처리 조정 | 아니요 |
| `db` | 5432 | PostgreSQL 17, pgvector | 아니요 |
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

## 3. 주요 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VLLM_MODEL_PATH` | `./google/google-gemma-4-12B-it-W4A16` | 호스트의 양자화 모델 경로 |
| `VLLM_MAX_MODEL_LEN` | `8192` | 최대 sequence length |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.65` | vLLM이 사용할 GPU 메모리 비율 |
| `VLLM_MAX_NUM_SEQS` | `4` | 동시에 처리할 최대 sequence 수 |
| `MAX_UPLOAD_BYTES` | `52428800` | 서버가 허용하는 PDF 파일 최대 바이트 수 |
| `READINESS_TIMEOUT_SECONDS` | `3` | readiness 구성요소별 최대 점검 시간(초) |
| 활성 retrieval preset | `balanced` | DB에서 관리하며 기본 `top_k=8`, 청크 `1000/150` |
| `AUTH_SESSION_TTL_HOURS` | `168` | 로그인 세션 유지 시간 |
| `AUTH_COOKIE_SECURE` | `false` | HTTPS 운영 환경에서는 `true`로 설정 |
| `BOOTSTRAP_ADMIN_USERNAME` | `admin` | 시작 시 보장할 개발용 관리자 사용자명 |
| `BOOTSTRAP_ADMIN_PASSWORD` | `admin` | 시작 시 보장할 개발용 관리자 비밀번호 |

`embedding`과 `llm`은 같은 GPU를 사용할 수 있습니다. `VLLM_GPU_MEMORY_UTILIZATION`은 전체 GPU 용량에 대한 목표치이며, 모델 weight, 실행 workspace, CUDA context와 KV cache가 함께 VRAM을 사용합니다.

## 4. API 계약

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/health` | API process 상태 |
| `GET` | `/health/ready` | DB, embedding, vLLM 통합 준비 상태 |
| `POST` | `/auth/register` | 공개 회원가입과 로그인 세션 발급 |
| `POST` | `/auth/login` | 로그인 세션 발급 |
| `POST` | `/auth/logout` | 현재 로그인 세션 폐기 |
| `GET` | `/auth/me` | 현재 로그인 사용자 |
| `POST` | `/documents` | multipart PDF 업로드 |
| `GET` | `/documents` | 문서 목록 |
| `GET` | `/documents/{id}` | 문서와 인덱싱 상태 |
| `GET` | `/documents/{id}/file` | 브라우저에서 여는 원본 PDF |
| `DELETE` | `/documents/{id}` | 문서, page/chunk와 원본 파일 삭제 |
| `POST` | `/chat` | 현재 사용자의 전체 indexed 문서 기반 질문 |
| `GET` | `/admin/retrieval` | 프리셋 목록, 활성 설정과 최근 작업 조회 |
| `POST` | `/admin/retrieval/presets/{key}/activate` | 프리셋 변경 작업 시작 |
| `POST` | `/admin/retrieval/algorithms/{key}/activate` | 검색 알고리즘 즉시 변경 |
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

공개 회원가입 계정은 기본적으로 `user` 역할입니다. 로컬 PoC에서는 API 시작 시
`admin/admin` 계정을 생성하거나 해당 계정의 역할과 비밀번호를 환경변수 값으로
맞춥니다. 외부 노출 환경에서는 `.env`의 기본 비밀번호를 반드시 변경합니다.

기존 계정을 추가 관리자로 지정하거나 권한을 회수할 때는 다음 CLI를 사용합니다.

```bash
docker compose exec api python -m app.cli.set_admin <username>
docker compose exec api python -m app.cli.set_admin --revoke <username>
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
`hybrid`는 세 결과의 Reciprocal Rank Fusion을 사용합니다. FTS와 trigram
인덱스는 상시 유지하므로 알고리즘 변경은 문서 재인덱싱 없이 즉시 적용됩니다.

`uploaded` 또는 `processing` 상태의 문서는 background indexing과 충돌하지
않도록 삭제 요청에 HTTP 409를 반환합니다. `indexed`와 `failed` 문서를
삭제하면 관련 pages, chunks, 해당 문서에 직접 연결된 기존 chat session과 원본
파일 디렉터리를 함께 제거합니다. 작업공간 chat session은 유지됩니다.

PDF 업로드는 `.pdf` 파일명과 PDF MIME type을 모두 요구합니다. 저장 중
`MAX_UPLOAD_BYTES`를 넘으면 HTTP 413을 반환하고, `%PDF-` 시그니처가 없거나
PyMuPDF가 열 수 없는 손상 파일 또는 암호화된 파일은 HTTP 400을 반환합니다.
거절된 업로드의 문서 DB 행과 부분 저장 파일은 즉시 정리됩니다. 텍스트가 없는
정상 PDF는 업로드 자체는 허용하지만 인덱싱 단계에서 `failed`로 전환됩니다.

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
      "document_title": "기본간호학.pdf",
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
제거하고 빈 `sources` 배열을 반환한다. 의료 상담성 질문의 안전 안내는 마커
뒤에 유지한다. `[[NO_SOURCE]`처럼 닫는 대괄호를 일부 누락해도 동일하게 처리한다.

## 5. 상태 확인

```bash
curl -sS http://localhost:8080/health
curl -sS http://localhost:8080/health/ready
curl -sS http://localhost:8070/health
curl -sS http://localhost:8010/v1/models
curl -sS -c session.cookie \
  -H 'Content-Type: application/json' \
  -d '{"username":"student01","password":"change-this-password"}' \
  http://localhost:8080/auth/register
curl -sS -b session.cookie http://localhost:8080/documents
curl -sS -b session.cookie -D - -o /dev/null http://localhost:8080/documents/1/file
```

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

다른 GPU 프로세스를 종료하거나 `.env`의 `VLLM_GPU_MEMORY_UTILIZATION`을 낮춥니다. 현재 기본값은 embedding service와의 공존을 고려한 `0.65`입니다.

### KV cache 부족

다음 형태의 오류는 설정한 최대 sequence length를 수용할 KV cache가 없다는 뜻입니다.

```text
KV cache is needed, which is larger than the available KV cache memory
```

`VLLM_MAX_MODEL_LEN`을 낮추거나, 여유 VRAM이 있다면 `VLLM_GPU_MEMORY_UTILIZATION`을 높입니다. 동시 요청 수가 중요하지 않은 개발 환경에서는 `VLLM_MAX_NUM_SEQS`도 낮출 수 있습니다.

### Gemma 4 W4A16 적재 오류

`Dockerfile.llm`은 Gemma 4 unified 모델의 compressed-tensors quantization 연결을 보완하는 로컬 vLLM patch를 적용합니다. 모델 구조 또는 vLLM base image가 바뀌면 patch 적용과 실제 completion 요청을 다시 검증해야 합니다.

## 7. 데이터 보존

- 원본 PDF: 호스트 `./data`, 컨테이너 `/app/data`
- PostgreSQL: Docker volume `postgres_data`
- Hugging Face cache: Docker volume `hf_cache`
- 양자화 모델: 호스트 `VLLM_MODEL_PATH`, 컨테이너에 read-only mount

`docker compose down`은 위 데이터를 삭제하지 않습니다. `down -v`는 DB와 cache volume을 제거하므로 데이터 삭제 의도가 있을 때만 사용합니다.

## 8. 현재 제한사항

- 이메일 확인, 비밀번호 재설정, 계정 잠금과 가입 rate limit이 없습니다.
- HTTP로 실행하는 로컬/LAN 기본 설정에서는 `AUTH_COOKIE_SECURE=false`입니다. 외부 운영 환경은 HTTPS와 `true` 설정이 필요합니다.
- 대화 생성 문맥은 최근 8개 메시지, 최대 8,000자로 제한됩니다. 검색 query는
  현재 질문만 사용하므로 대명사 위주의 후속 질문은 구체적인 용어를 포함한
  질문보다 검색 recall이 낮을 수 있습니다.
- 질문은 로그인 사용자의 모든 `indexed` 문서를 검색하며, 처리 중이거나 실패한
  문서는 검색 대상에서 제외됩니다.
- 문서 처리는 API process의 `BackgroundTasks`를 사용하며 재시작 시 처음부터 복구하지만 별도 worker/queue가 없어 API process 수명과 자원을 공유합니다.
- 프리셋 재인덱싱은 DB 작업 상태를 이용해 API 재시작 시 처음부터 복구하지만 별도 worker/queue가 없어 API process 수명과 자원을 공유합니다.
- 텍스트 기반 PDF만 처리하며 scanned PDF용 OCR은 없습니다.
- 답변은 streaming하지 않습니다.

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
- 서로 다른 두 사용자 간 문서 목록·원본 PDF·질의·삭제 접근 격리
- 데스크톱·모바일 인증 UI와 모바일 가로 overflow 없음
- 관리자 권한 격리, 프리셋 5개 조회·전환·진행 상태 UI
- 실제 PDF의 프리셋 변경 재청킹, 대화 정리와 index version 갱신
- 재인덱싱 유지보수 모드와 문서 질문/삭제 동시성 제어
- API 재시작 후 중단된 재인덱싱 작업의 자동 복구
- API 재시작 후 `uploaded/processing` PDF의 자동 재인덱싱과 누락 원본 실패 처리
- Dense, FTS Keyword, pg_trgm Substring과 RRF Hybrid 검색 결과
- 관리자 UI의 청킹 preset·검색 알고리즘 독립 전환과 모바일 overflow 없음
- 서버의 업로드 크기, 확장자, MIME, PDF 시그니처·구조·암호화 검증
- DB, embedding, vLLM 통합 readiness와 API Docker healthcheck

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

테스트 DB의 이름과 계정은 운영 설정과 다르며 운영 DB port `5432`,
`postgres_data`, `data/` 업로드 파일을 사용하지 않습니다. embedding과 LLM
클라이언트는 테스트 대역으로 교체하므로 GPU 서비스도 필요하지 않습니다.

현재 자동화 범위는 프리셋 유효성·변경 영향, 인증 입력, RRF 병합, 회원가입과
세션, 사용자별 문서 격리, PDF 업로드·삭제 제약, 대화 저장·복원·소유권·페이지 조회, 관리자 권한과
프리셋 전환, 네 검색 알고리즘의 실제 PostgreSQL 질의, 문서 및 재인덱싱 복구를
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

E2E Compose project는 운영 `embedding`과 `llm` endpoint만 공유합니다. API,
PostgreSQL, 관리자 계정, 업로드 경로는 다음과 같이 격리되고 테스트 종료 시
자동 삭제됩니다.

| 자원 | E2E 값 |
|---|---|
| API | `127.0.0.1:18080` |
| PostgreSQL | `127.0.0.1:55433`, tmpfs |
| DB 이름 | `rag_e2e_db` |
| PDF fixture | `sample_fall_prevention.pdf` |

검증 범위는 실제 PDF 4페이지 파싱, BGE-M3 1024차원 임베딩 저장, 고유 정답과
page 1 출처 검색, 자료에 없는 질문 제한, 실제 환자 산소 투여량 질문에 대한
안전 안내, 테스트 문서 삭제입니다. 생성 모델 결과는 문장 전체가 아니라 필수
용어, 출처 page, 금지된 구체 처치 지시 여부로 판정합니다.
