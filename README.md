# Nursing PDF RAG Tutor PoC

간호학 수업자료 PDF를 업로드하고, 자료에 근거한 답변과 원문 페이지 출처를 제공하는 RAG 학습 튜터 PoC입니다. 의료 상담, 진단 또는 처방을 위한 시스템이 아닙니다.

## 구성

```text
Browser
  -> api        FastAPI API + Vanilla HTML/CSS/JS Web UI
       -> db    PostgreSQL 17 + pgvector
       -> embedding  BAAI/bge-m3 embedding service
       -> llm   vLLM OpenAI-compatible Gemma 4 endpoint
```

런타임은 `api`, `db`, `embedding`, `llm` 네 컨테이너로 구성됩니다. Web UI는 API 컨테이너가 정적 파일로 제공하므로 별도 프런트엔드 컨테이너나 빌드 단계가 없습니다.

## 사전 준비

- Docker Engine과 Docker Compose
- NVIDIA GPU, 호스트 드라이버, NVIDIA Container Toolkit
- 프로젝트 루트의 Gemma 4 12B W4A16 모델 디렉터리
- 의존성 관리 도구 `uv` (로컬 개발 시)

기본 모델 경로는 `./google/google-gemma-4-12B-it-W4A16`입니다. 다른 위치를 사용하려면 `.env`의 `VLLM_MODEL_PATH`를 변경합니다.

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
`인덱싱 완료`가 될 때까지 기다린 후 질문합니다. 문서와 대화는 로그인한
사용자별로 분리되며, 답변 아래의 페이지 버튼을 누르면 원본 PDF의 해당
페이지가 열립니다.

로컬 PoC 기본 관리자는 `admin/admin`입니다. 로그인 후 화면 상단의 `관리자`
버튼에서 검색 프리셋을 변경하고 재인덱싱 진행 상태를 확인할 수 있습니다.
이 계정은 API 시작 시 생성되며 `.env`의 `BOOTSTRAP_ADMIN_USERNAME`과
`BOOTSTRAP_ADMIN_PASSWORD`로 변경해야 합니다.

기존 일반 계정을 추가 관리자로 지정할 때는 CLI를 사용합니다.

```bash
docker compose exec api python -m app.cli.set_admin <username>
```

`admin/admin`은 로컬 검증용 자격 증명입니다. LAN 외부에 서비스를 노출하기
전에는 반드시 긴 비밀번호로 변경하고 HTTPS를 적용합니다.

## 로컬 API 개발

DB, embedding, LLM은 컨테이너로 실행하고 API만 호스트에서 구동할 수 있습니다.

```bash
cp .env.example .env
docker compose up -d db embedding
docker compose --profile llm up -d llm
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8080
```

## 기본 점검

```bash
curl http://localhost:8080/health
curl http://localhost:8080/health/ready
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
tmpfs 테스트 DB는 `55433`에 따로 기동합니다. 운영 DB와 업로드 문서는 사용하지
않습니다. 샘플 PDF의 파싱·임베딩·검색·답변·출처와 자료 외 질문 및 의료
상담성 질문의 안전 동작을 검증합니다.

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
  -d '{"question":"업로드한 자료의 핵심 내용을 설명해 주세요."}' \
  http://localhost:8080/chat
```

## 문서

- [요구사항 및 데이터 설계](task.md)
- [프런트엔드 요구사항과 구조 설계](docs/frontend-design.md)
- [검색 preset 요구사항](docs/retrieval-presets.md)
- [운영, 검증 및 문제 해결](docs/operations.md)

## 현재 MVP 범위

- PDF 추가·삭제, 텍스트 추출, page 단위 chunking 및 BGE-M3 embedding
- 50MB 서버 제한, PDF 시그니처·구조·암호화 여부 업로드 검증
- 공개 회원가입, 로그인·로그아웃과 사용자별 문서·대화 격리
- pgvector Dense, PostgreSQL FTS, pg_trgm 및 RRF Hybrid 검색
- 로그인 사용자의 모든 indexed 문서를 대상으로 하는 작업공간 RAG 검색
- Gemma 4 12B W4A16 모델을 사용한 답변 생성
- 답변 출처와 원본 PDF 페이지 연결
- 반응형 Web UI와 문서 처리 상태 polling
- 관리자 청킹 프리셋 5개, 검색 알고리즘 4개와 변경 영향 판정
- API 재시작 시 중단된 PDF 인덱싱과 전체 재인덱싱 자동 복구
- DB, embedding, vLLM 통합 readiness와 Docker 시작 상태 연동

이메일 확인, 비밀번호 재설정, 대화 이력 조회, OCR,
스트리밍 답변과 영속 작업 큐는 후속 범위입니다.
