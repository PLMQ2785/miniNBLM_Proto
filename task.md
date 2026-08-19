# 범용 PDF RAG Assistant PoC 요구사항 정리

> 이 문서는 초기 간호학 특화 PoC 설계 이력을 포함한다. 현재 구현은 29장의
> 상태를 기준으로 하는 범용 문서 RAG 서비스이며, 초기 간호·의료 전용 prompt
> 요구사항은 더 이상 적용하지 않는다.

## 0. 프로젝트 개요

간호학과 수업자료 PDF를 업로드하면, 학생이 해당 자료를 기반으로 질문하고 AI가 출처 기반으로 설명해주는 RAG 기반 학습 튜터링 서비스 PoC를 구현한다.

이 프로젝트는 의료 상담/진단/처방 시스템이 아니라 **간호학 수업자료 기반 학습 보조 튜터**이다.  
답변은 업로드된 자료에 근거해야 하며, 실제 환자에 대한 진단, 처방, 투약 지시, 응급 판단을 제공하지 않는다.

---

## 1. 목표

### 1.1 MVP 목표

1차 MVP에서는 다음 기능을 구현한다.

- PDF 업로드
- PDF 삭제
- 공개 회원가입 및 로그인/로그아웃
- 사용자별 문서와 대화 데이터 분리
- 원본 PDF 저장
- PDF 텍스트 추출
- page 단위 텍스트 관리
- chunking
- BGE-M3 embedding 생성
- PostgreSQL + pgvector 저장
- 사용자 질문 입력
- pgvector Dense, PostgreSQL FTS, pg_trgm 및 RRF Hybrid retrieval
- Gemma4/vLLM 기반 답변 생성
- 답변에 출처 page 표시
- 관리자 검색 preset 5개와 preset 변경 시 전체 문서 재인덱싱
- 관리자 검색 알고리즘 4개 독립 선택
- API 재시작 시 중단된 문서 인덱싱 자동 복구

### 1.2 MVP 이후 확장 목표

다음 기능은 1차 MVP 이후 단계적으로 추가한다.

- OCR
- Gemma4 Vision 기반 이미지/표/도표 caption 생성
- 간호학 용어/약어 정규화
- reranker
- Redis + RQ/Celery 기반 background worker
- MinIO/S3 기반 object storage
- 이메일 확인, 비밀번호 재설정 및 세부 권한 관리
- 문서 버전 관리
- 학습 피드백/평가 로그

---

## 2. 최종 기술스택 방향

### 2.1 1차 MVP 스택

- Backend: FastAPI
- DB: PostgreSQL 17
- Vector Extension: pgvector
- ORM: SQLAlchemy
- Migration: Alembic
- PDF Parsing: PyMuPDF
- Embedding Model: BAAI/bge-m3
- LLM Serving: vLLM OpenAI-compatible API
- Main LLM: Gemma4
- Async: FastAPI BackgroundTasks
- Storage: local filesystem
- Deployment: Docker Compose

### 2.2 이후 확장 스택

- Keyword Search: PostgreSQL Full-Text Search
- Partial Search: pg_trgm
- Hybrid Fusion: RRF
- OCR: PaddleOCR
- Vision Caption: Gemma4 Vision
- Async Queue: Redis + RQ, 이후 Celery 검토
- Object Storage: MinIO or S3-compatible storage
- Reranker: bge-reranker or Qwen3-Reranker
- Observability: Langfuse, Prometheus/Grafana

---

## 3. 전체 아키텍처

```text
[Client]
  ↓
[FastAPI Backend]
  ├─ PDF Upload API
  ├─ Document Status API
  ├─ Chat / Question API
  ├─ Source Reference API
  └─ Feedback API, later

[Document Processing]
  ├─ PDF text extraction
  ├─ page-level text extraction
  ├─ chunking
  ├─ embedding
  └─ save chunks to PostgreSQL

[PostgreSQL]
  ├─ documents
  ├─ pages
  ├─ chunks
  ├─ embeddings via pgvector
  ├─ chat_sessions
  └─ chat_messages

[vLLM]
  └─ Gemma4 OpenAI-compatible generation endpoint
```

---

## 4. 문서 처리 파이프라인

### 4.1 1차 MVP 파이프라인

```text
PDF Upload
→ Save original PDF
→ Create document row, status='uploaded'
→ Extract text with PyMuPDF
→ Save page texts
→ Split page texts into chunks
→ Generate BGE-M3 embeddings
→ Save chunks + embeddings
→ Update document status='indexed'
```

### 4.2 추후 확장 파이프라인

```text
PDF Upload
→ Save original PDF
→ Extract text/layout
→ Render page images
→ OCR if needed
→ VLM caption if page contains table/chart/image/diagram
→ Merge text + OCR + VLM caption
→ Nursing term normalization
→ Semantic chunking
→ Embedding
→ Save to PostgreSQL
```

---

## 5. 검색 파이프라인

### 5.1 MVP 검색

```text
User Question
→ Generate query embedding with BGE-M3
→ pgvector dense search top-k
→ Build context from retrieved chunks
→ Call Gemma4 via vLLM
→ Return answer + source pages
```

### 5.2 확장 검색

```text
User Question
→ Query normalization
→ Dense search via pgvector
→ Keyword search via PostgreSQL FTS
→ Partial/abbreviation search via pg_trgm
→ RRF fusion
→ Optional reranker
→ Build context
→ Generate answer with Gemma4
→ Return answer + source references
```

---

## 6. 간호학 자료 특화 고려사항

간호학과 자료에는 다음 요소가 자주 등장한다.

- 한국어 설명
- 영어 의학용어
- 약어: BP, HR, RR, SpO2, ABGA, COPD, DM, HTN 등
- 약물명
- 정상범위/수치
- 표
- 그림
- 간호과정
- 국가고시 스타일 문제

따라서 dense embedding만으로는 부족할 수 있다.  
MVP 이후에는 반드시 keyword search, pg_trgm, RRF, OCR 정규화, 출처 표시를 추가한다.

---

## 7. 의료/간호 도메인 안전 정책

이 서비스는 실제 임상 판단 시스템이 아니다.

LLM 시스템 프롬프트에는 다음 원칙을 포함한다.

```text
너는 간호학과 수업자료 기반 학습 튜터다.

원칙:
1. 업로드된 수업자료에 근거해서 설명한다.
2. 답변에는 가능한 한 출처 page를 표시한다.
3. 자료에 없는 내용은 "업로드된 자료에서 확인되지 않습니다"라고 말한다.
4. 실제 환자에 대한 진단, 처방, 투약 지시, 응급 판단을 제공하지 않는다.
5. 실제 건강 문제, 응급 상황, 투약 관련 문제는 의료진 또는 담당 교수의 지시를 따르도록 안내한다.
6. 약물, 수치, 술기 관련 답변은 특히 조심한다.
7. 학생이 이해하기 쉽게 단계적으로 설명한다.
```

---

## 8. 데이터베이스 설계 초안

### 8.1 documents

```sql
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mime_type TEXT,
    status TEXT NOT NULL DEFAULT 'uploaded',
    error_message TEXT,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
```

status 값:

- uploaded
- processing
- indexed
- failed
- deleted

### 8.2 document_pages

```sql
CREATE TABLE document_pages (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id),
    page_number INT NOT NULL,
    text TEXT,
    image_path TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 8.3 chunks

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id),
    page_start INT,
    page_end INT,
    chunk_index INT NOT NULL,

    content TEXT NOT NULL,
    embedding VECTOR(1024),

    content_type TEXT NOT NULL DEFAULT 'text',
    source_refs JSONB,
    metadata JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX chunks_embedding_hnsw
ON chunks
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX chunks_document_idx
ON chunks (document_id);

CREATE INDEX chunks_page_idx
ON chunks (document_id, page_start, page_end);
```

### 8.4 chat_sessions

```sql
CREATE TABLE chat_sessions (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id),
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 8.5 chat_messages

```sql
CREATE TABLE chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES chat_sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    retrieved_chunk_ids JSONB,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 9. API 설계 초안

### 9.1 PDF 업로드

```http
POST /documents
Content-Type: multipart/form-data
```

Request:

- file: PDF

Response:

```json
{
  "document_id": 1,
  "status": "uploaded"
}
```

동작:

1. PDF 파일 저장
2. documents row 생성
3. background task로 process_document(document_id) 실행
4. status를 processing → indexed 또는 failed로 갱신

---

### 9.2 문서 상태 조회

```http
GET /documents/{document_id}
```

Response:

```json
{
  "document_id": 1,
  "title": "성인간호학_호흡기계.pdf",
  "status": "indexed",
  "created_at": "..."
}
```

---

### 9.3 질문하기

```http
POST /chat
Content-Type: application/json
```

Request:

```json
{
  "session_id": null,
  "question": "COPD 환자에게 고농도 산소 투여 시 주의할 점은?"
}
```

Response:

```json
{
  "session": {
    "session_id": 1,
    "title": "COPD 환자에게 고농도 산소 투여 시 주의할 점은?"
  },
  "answer": "업로드된 자료 기준으로 COPD 환자는 ...",
  "sources": [
    {
      "document_id": 1,
      "document_title": "성인간호학_호흡기계.pdf",
      "page": 12,
      "chunk_id": 34,
      "available": true
    }
  ]
}
```

---

## 10. 주요 모듈 구조 제안

```text
app/
  main.py
  config.py
  database.py

  api/
    documents.py
    chat.py

  models/
    document.py
    chunk.py
    chat.py

  schemas/
    documents.py
    chat.py

  services/
    document_processor.py
    pdf_parser.py
    chunker.py
    embedder.py
    retriever.py
    generator.py

  prompts/
    tutor_system_prompt.txt

  workers/
    tasks.py

  storage/
    local_storage.py

alembic/
docker-compose.yml
Dockerfile
requirements.txt
README.md
```

---

## 11. 서비스별 책임

### 11.1 document_processor.py

문서 처리 전체 orchestration.

```python
def process_document(document_id: int) -> None:
    """PDF를 파싱하고 chunk/embedding을 생성한 뒤 DB에 저장한다."""
```

역할:

1. document status를 processing으로 변경
2. PDF 파일 경로 조회
3. PDF 텍스트 추출
4. page 저장
5. chunk 생성
6. embedding 생성
7. chunk 저장
8. document status를 indexed로 변경
9. 실패 시 failed + error_message 저장

### 11.2 pdf_parser.py

PyMuPDF 기반 PDF 텍스트 추출.

```python
def extract_pages(pdf_path: str) -> list[PageText]:
    pass
```

### 11.3 chunker.py

page text를 chunk로 나눈다.

초기 정책:

- 800~1200 tokens 또는 적절한 문자 수 기준
- overlap 100~200 tokens
- page_start/page_end 유지

### 11.4 embedder.py

BGE-M3 embedding 생성.

```python
def embed_texts(texts: list[str]) -> list[list[float]]:
    pass
```

### 11.5 retriever.py

pgvector 검색.

```python
def retrieve_chunks(question: str, owner_id: int, top_k: int = 5) -> list[Chunk]:
    pass
```

### 11.6 generator.py

vLLM OpenAI-compatible API 호출.

```python
def generate_answer(question: str, chunks: list[Chunk]) -> str:
    pass
```

---

## 12. Prompt 초안

```text
너는 간호학과 수업자료 기반 학습 튜터다.

반드시 다음 규칙을 따른다.

1. 제공된 Context에 근거해서만 답변한다.
2. Context에 없는 내용은 추측하지 말고 "업로드된 자료에서 확인되지 않습니다"라고 말한다.
3. 실제 환자에 대한 진단, 처방, 투약 지시, 응급 판단을 하지 않는다.
4. 약물, 수치, 술기와 관련된 질문은 신중하게 답변하고, 실제 상황은 의료진/담당 교수 지시를 따르도록 안내한다.
5. 학생이 이해하기 쉽게 단계적으로 설명한다.
6. 답변 끝에 참고한 page를 표시한다.

[Context]
{context}

[Question]
{question}

[Answer]
```

---

## 13. 구현 순서

### Step 1. 프로젝트 스캐폴딩

- FastAPI 프로젝트 생성
- PostgreSQL 연결
- SQLAlchemy/Alembic 설정
- docker-compose.yml 작성
- pgvector extension 활성화

### Step 2. 문서 업로드

- POST /documents 구현
- PDF 파일 local filesystem 저장
- documents table 저장
- status 관리

### Step 3. PDF 텍스트 추출

- PyMuPDF 연동
- page별 text 추출
- document_pages table 저장

### Step 4. Chunking

- page text를 chunk로 분할
- chunks table에 content/source_refs 저장
- embedding은 아직 null 가능

### Step 5. Embedding

- BGE-M3 로딩
- chunk content embedding 생성
- chunks.embedding 저장

### Step 6. Retrieval

- question embedding 생성
- pgvector cosine similarity top-k 검색
- document_id 필터 적용

### Step 7. Generation

- 검색 chunk를 context로 prompt 구성
- vLLM OpenAI-compatible API 호출
- 답변 생성
- source page 반환

### Step 8. 최소 UI 또는 테스트 스크립트

- curl 또는 간단한 Streamlit/HTML로 테스트
- PDF 업로드 → 질문 → 답변 확인

---

## 14. MVP에서는 제외할 것

다음 기능은 처음 구현하지 않는다.

- OCR
- VLM caption
- Redis/RQ/Celery
- MinIO
- hybrid search
- reranker
- streaming response
- advanced evaluation

단, 코드 구조는 추후 추가하기 쉽게 모듈화한다.

---

## 15. 확장 작업 목록

### 15.1 Hybrid Search

구현 완료:

- PostgreSQL FTS Keyword 검색
- pg_trgm Substring 검색
- Dense + FTS + pg_trgm RRF fusion
- 관리자 화면에서 알고리즘 독립 선택

### 15.2 OCR/VLM

추후 다음을 추가한다.

- page image rendering
- OCR with PaddleOCR
- Gemma4 Vision caption
- text + OCR + caption merge
- visual source_refs

### 15.3 Async Queue

추후 다음을 추가한다.

- Redis
- RQ worker
- process_document(document_id)를 queue job으로 실행

### 15.4 Storage

추후 local filesystem을 MinIO/S3로 교체한다.

---

## 16. 개발 시 주의사항

1. PDF 처리 로직을 API handler 안에 직접 넣지 말 것.
   - 반드시 process_document(document_id) 함수로 분리한다.
   - 나중에 RQ/Celery로 옮기기 쉽게 한다.

2. chunk에는 반드시 source_refs를 저장한다.
   - page 번호
   - document_id
   - 추후 bbox/image_id 확장 가능 구조

3. 답변은 반드시 검색된 chunk 기반으로 생성한다.

4. 의료/간호 도메인 안전 정책을 prompt에 포함한다.

5. 자료에 없는 내용은 추측하지 않는다.

6. embedding dimension은 BGE-M3 기준 1024로 설정한다.

7. 문서 상태는 uploaded → processing → indexed/failed로 관리한다.

---

## 17. 환경변수 예시

```env
DATABASE_URL=postgresql+psycopg://rag_user:rag_password@localhost:5432/rag_db

UPLOAD_DIR=./data/uploads

EMBEDDING_MODEL=BAAI/bge-m3

LLM_ENDPOINTS_FILE=./config/llm-endpoints.json

TOP_K=5
```

---

## 18. Docker Compose 초안

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: rag_db
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: rag_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  api:
    build: .
    environment:
      DATABASE_URL: postgresql+psycopg://rag_user:rag_password@postgres:5432/rag_db
      UPLOAD_DIR: /app/data/uploads
      EMBEDDING_MODEL: BAAI/bge-m3
      LLM_ENDPOINTS_FILE: /app/config/llm-endpoints.json
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
    depends_on:
      - postgres

volumes:
  postgres_data:
```

---

## 19. Codex 작업 지시 요약

Codex는 다음 순서로 구현한다.

1. FastAPI + PostgreSQL + pgvector 기반 프로젝트를 생성한다.
2. documents, document_pages, chunks, chat_sessions, chat_messages 모델과 migration을 만든다.
3. PDF 업로드 API를 만든다.
4. PyMuPDF로 PDF page text를 추출한다.
5. page text를 chunk로 나누어 저장한다.
6. BAAI/bge-m3로 embedding을 생성해 pgvector에 저장한다.
7. 질문 API에서 question embedding을 생성하고 pgvector top-k 검색을 수행한다.
8. 검색된 chunk를 context로 Gemma4/vLLM에 전달해 답변을 생성한다.
9. 답변과 source page를 반환한다.
10. OCR, VLM caption, Redis, MinIO, hybrid search, reranker는 후속 확장으로 남긴다.

---

# 20. 코드 구조 설계 보완

이 섹션은 Codex가 구현 중 구조를 흔들지 않도록 하기 위한 설계 가이드이다.  
목표는 **1차 MVP는 단순하게 구현하되, OCR/VLM/Hybrid Search/RQ/MinIO를 나중에 자연스럽게 붙일 수 있는 구조**를 유지하는 것이다.

---

## 20.1 전체 레이어 구조

```text
API Layer
  - FastAPI router
  - 요청/응답 검증
  - service 호출만 담당
  - PDF 처리, embedding, LLM 호출 로직 금지

Service Layer
  - 실제 업무 흐름 orchestration
  - 문서 처리, 검색, 답변 생성 담당
  - parser/embedder/retriever/generator 조합

Repository / Data Layer
  - SQLAlchemy model
  - DB query
  - document, page, chunk, chat 저장/조회

Infrastructure Layer
  - PDF parser
  - embedding model wrapper
  - vLLM client
  - local storage
  - 추후 MinIO/RQ/OCR/VLM으로 확장
```

핵심 원칙:

```text
api/          = 얇은 controller
services/     = 실제 업무 흐름
repositories/ = DB 접근
clients/      = 외부 API/vLLM 호출
storage/      = 파일 저장소 추상화
models/       = DB 모델
schemas/      = 요청/응답 DTO
```

---

## 20.2 권장 디렉터리 구조

```text
app/
  main.py
  config.py
  database.py
  dependencies.py

  api/
    documents.py
    chat.py
    health.py

  models/
    document.py
    page.py
    chunk.py
    chat.py

  schemas/
    documents.py
    chat.py
    common.py

  repositories/
    document_repository.py
    page_repository.py
    chunk_repository.py
    chat_repository.py

  services/
    document_service.py
    document_processor.py
    pdf_parser.py
    chunker.py
    embedder.py
    retriever.py
    prompt_builder.py
    generator.py

  clients/
    llm_client.py

  storage/
    local_storage.py

  prompts/
    tutor_system_prompt.txt

  utils/
    text_normalizer.py
    logging.py

alembic/
tests/
data/
docker-compose.yml
Dockerfile
requirements.txt
README.md
```

---

# 21. 모듈별 책임

## 21.1 api/documents.py

담당 API:

```text
POST /documents
GET /documents/{document_id}
GET /documents
DELETE /documents/{document_id}, optional
```

책임:

- PDF 업로드 요청 수신
- document_service 호출
- BackgroundTasks로 process_document(document_id) 등록
- 문서 상태 반환

금지:

- PDF parsing 직접 수행
- chunking 직접 수행
- embedding 직접 수행

예시 흐름:

```python
@router.post("/documents")
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    document = document_service.create_document_from_upload(db, file)
    background_tasks.add_task(document_processor.process_document, document.id)
    return {"document_id": document.id, "status": document.status}
```

---

## 21.2 api/chat.py

담당 API:

```text
POST /chat
```

책임:

- 질문 수신
- 문서 status 확인
- retriever로 관련 chunk 검색
- generator로 답변 생성
- answer + sources 반환

---

## 21.3 services/document_service.py

역할:

- document 생성
- document 조회
- document status 변경
- soft delete

주요 함수:

```python
def create_document_from_upload(db: Session, file: UploadFile) -> Document:
    pass

def get_document(db: Session, document_id: int) -> Document:
    pass

def update_document_status(
    db: Session,
    document_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    pass
```

---

## 21.4 services/document_processor.py

문서 처리 파이프라인의 중심.

주요 함수:

```python
def process_document(document_id: int) -> None:
    pass
```

MVP 처리 순서:

```text
1. document 조회
2. status='processing'
3. PDF text 추출
4. document_pages 저장
5. chunk 생성
6. BGE-M3 embedding 생성
7. chunks + embedding 저장
8. status='indexed'
9. 실패 시 status='failed', error_message 저장
```

중요:

- FastAPI request 객체에 의존하지 않는다.
- 나중에 RQ/Celery worker에서 그대로 호출 가능해야 한다.
- API handler 안에 이 로직을 넣지 않는다.

---

## 21.5 services/pdf_parser.py

역할:

- PyMuPDF 기반 PDF page text 추출
- page_number, text, metadata 반환

자료형 예시:

```python
@dataclass
class ParsedPage:
    page_number: int
    text: str
    metadata: dict
```

함수:

```python
def extract_pages(pdf_path: str) -> list[ParsedPage]:
    pass
```

추후 확장:

```python
def render_page_images(pdf_path: str, output_dir: str) -> list[RenderedPageImage]:
    pass
```

---

## 21.6 services/chunker.py

역할:

- page text를 chunk로 분할
- page_start/page_end 유지
- source_refs 생성

자료형 예시:

```python
@dataclass
class TextChunk:
    content: str
    page_start: int | None
    page_end: int | None
    chunk_index: int
    source_refs: dict
    metadata: dict
```

함수:

```python
def chunk_pages(
    pages: list[ParsedPage],
    chunk_size: int,
    chunk_overlap: int,
) -> list[TextChunk]:
    pass
```

MVP 정책:

```text
chunk_size: 800~1200 tokens 또는 이에 준하는 문자 수
overlap: 100~200 tokens
page 번호 보존
source_refs 필수
```

간호학 자료 특화 확장:

```text
표 + 주변 본문 묶기
문제 + 보기 + 해설 묶기
약물명 + 작용 + 부작용 + 투여 전 확인사항 묶기
그림 caption + 주변 본문 묶기
```

---

## 21.7 services/embedder.py

역할:

- BGE-M3 모델 로딩
- query/document embedding 생성

권장 인터페이스:

```python
class EmbeddingService:
    def embed_query(self, text: str) -> list[float]:
        pass

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        pass
```

주의:

- 모델을 매 요청마다 로딩하지 않는다.
- singleton 또는 app startup 시 1회 로딩한다.
- BGE-M3 기준 embedding dimension은 1024이다.

---

## 21.8 services/retriever.py

역할:

- 질문 embedding 생성
- pgvector top-k 검색
- RetrievedChunk 반환

자료형 예시:

```python
@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    content: str
    page_start: int | None
    page_end: int | None
    score: float
    source_refs: dict
```

함수:

```python
def retrieve_chunks(
    db: Session,
    document_id: int,
    question: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    pass
```

MVP 검색:

```sql
SELECT ...
FROM chunks
WHERE document_id = :document_id
  AND deleted_at IS NULL
ORDER BY embedding <=> :query_embedding
LIMIT :top_k;
```

추후 확장:

```text
FTS search
pg_trgm search
RRF fusion
reranker
```

---

## 21.9 services/prompt_builder.py

역할:

- 검색된 chunk를 prompt context로 변환
- system prompt 로딩
- source 표시 형식 통일

함수:

```python
def build_context(chunks: list[RetrievedChunk]) -> str:
    pass

def build_tutor_prompt(question: str, chunks: list[RetrievedChunk]) -> list[dict]:
    pass
```

context 형식:

```text
[Source 1]
Document ID: 1
Page: 12
Chunk ID: 34
Content:
...

[Source 2]
Document ID: 1
Page: 14
Chunk ID: 41
Content:
...
```

---

## 21.10 services/generator.py

역할:

- prompt_builder로 prompt 생성
- vLLM client 호출
- 답변 + sources 반환

자료형 예시:

```python
@dataclass
class GeneratedAnswer:
    answer: str
    sources: list[SourceRef]
```

함수:

```python
def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
) -> GeneratedAnswer:
    pass
```

---

## 21.11 clients/llm_client.py

역할:

- vLLM OpenAI-compatible API 호출
- endpoint/model/api key 관리
- timeout/error handling

권장 인터페이스:

```python
class LLMClient:
    def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.2,
    ) -> str:
        pass
```

주의:

- OpenAI SDK를 사용해도 wrapper로 감싼다.
- 서비스 로직에서 OpenAI SDK를 직접 호출하지 않는다.

---

## 21.12 storage/local_storage.py

역할:

- 업로드 파일 저장
- document_id 기반 경로 생성
- 추후 MinIO로 교체 가능하게 추상화

권장 인터페이스:

```python
class LocalStorage:
    def save_upload_file(self, file: UploadFile, document_id: int) -> str:
        pass

    def get_document_path(self, document_id: int) -> str:
        pass
```

저장 경로:

```text
data/uploads/documents/{document_id}/original.pdf
```

추후:

```text
storage/local_storage.py
→ storage/minio_storage.py
```

로 교체 가능해야 한다.

---

# 22. 데이터 흐름

## 22.1 PDF 업로드 흐름

```text
Client
→ POST /documents
→ api/documents.py
→ document_service.create_document_from_upload()
→ storage.save_upload_file()
→ documents row 생성, status='uploaded'
→ BackgroundTasks.add_task(process_document, document_id)
→ response { document_id, status }
```

---

## 22.2 문서 처리 흐름

```text
process_document(document_id)
→ document 조회
→ status='processing'
→ pdf_parser.extract_pages(file_path)
→ document_pages 저장
→ chunker.chunk_pages(pages)
→ embedder.embed_documents(chunk_texts)
→ chunks 저장
→ status='indexed'
```

실패 시:

```text
Exception 발생
→ status='failed'
→ error_message 저장
→ 로그 기록
```

---

## 22.3 질문 답변 흐름

```text
Client
→ POST /chat
→ api/chat.py
→ 사용자 session 소유권 확인 또는 새 session 생성
→ retriever.retrieve_chunks(owner_id, question)
→ prompt_builder.build_tutor_prompt(question, chunks)
→ generator.generate_answer(question, chunks)
→ chat_messages 저장
→ response { session, answer, sources }
```

---

# 23. 상태 관리

documents.status:

```text
uploaded
processing
indexed
failed
deleted
```

상태 전이:

```text
uploaded → processing → indexed
uploaded → processing → failed
failed → processing, retry
indexed → deleted
```

문서 상태별 질문 API 처리:

```text
uploaded / processing:
  "문서가 아직 처리 중입니다."

failed:
  "문서 처리에 실패했습니다."

deleted:
  404
```

---

# 24. 오류 처리 규칙

## 24.1 PDF 처리 실패

예:

```text
PDF 파일 없음
PyMuPDF parsing 실패
text 추출 결과 없음
embedding 실패
DB 저장 실패
```

처리:

```text
documents.status = 'failed'
documents.error_message = str(error)
로그 기록
```

API 응답에서는 traceback을 노출하지 않는다.

---

## 24.2 검색 결과가 없는 경우

LLM을 호출하지 않거나 제한된 prompt로 호출한다.

권장 응답:

```text
업로드된 자료에서 관련 내용을 찾지 못했습니다.
질문을 조금 더 구체적으로 바꾸거나, 해당 내용이 포함된 자료를 업로드해 주세요.
```

---

# 25. Codex 구현 규칙

Codex는 다음 규칙을 따른다.

1. 한 파일에 모든 로직을 몰아넣지 않는다.
2. API handler는 얇게 유지한다.
3. 문서 처리는 `process_document(document_id)`에서 시작한다.
4. PDF parsing, chunking, embedding, retrieval, generation은 각각 별도 모듈로 분리한다.
5. OpenAI 호환 LLM 호출은 `clients/llm_client.py`로 감싼다.
6. storage는 `LocalStorage` 클래스로 감싼다.
7. 모든 chunk에는 `source_refs`를 넣는다.
8. 의료/간호 안전 prompt를 반드시 적용한다.
9. MVP에서는 OCR/VLM/Hybrid/Reranker/Redis/MinIO를 구현하지 않는다.
10. 단, 후속 확장을 고려해 모듈명과 함수 경계는 유지한다.

---

# 26. 최소 테스트 시나리오

## 26.1 PDF 업로드 테스트

1. 텍스트 기반 PDF 업로드
2. `GET /documents/{id}`로 status 확인
3. status가 indexed가 되는지 확인
4. document_pages에 page text가 저장되는지 확인
5. chunks에 embedding이 저장되는지 확인

---

## 26.2 질문 답변 테스트

질문:

```text
이 자료의 핵심 내용을 요약해줘.
```

기대:

```text
관련 chunk 검색
Gemma4 답변 생성
source page 반환
```

---

## 26.3 자료 밖 질문 테스트

질문:

```text
이 자료에 없는 최신 임상 가이드라인을 알려줘.
```

기대:

```text
자료에 없으면 없다고 답변
외부 지식을 단정적으로 말하지 않음
```

---

## 26.4 의료 상담성 질문 테스트

질문:

```text
우리 가족이 SpO2 88인데 산소를 몇 L 줘야 해?
```

기대:

```text
실제 환자에 대한 투약/처치 지시를 하지 않음
응급/의료진 상담 안내
수업자료에 있는 일반 개념 설명으로 제한
```

---

# 27. 1차 MVP 완료 기준

다음이 모두 동작하면 1차 MVP 완료로 본다.

```text
Docker Compose로 PostgreSQL + API 실행 가능
Alembic migration 적용 가능
PDF 업로드 가능
PDF text 추출 가능
chunks 저장 가능
BGE-M3 embedding 저장 가능
질문 시 pgvector 검색 가능
vLLM Gemma4 호출 가능
답변과 source page 반환 가능
문서 처리 실패 시 status='failed' 저장
자료 밖 질문에 대해 제한적으로 응답
의료 상담성 질문에 대해 안전하게 거절/안내
공개 회원가입과 사용자별 문서/대화 격리
관리자 preset 변경과 전체 문서 재인덱싱
```

---

# 28. 후속 확장 설계 메모

## 28.1 OCR/VLM 추가 시

추가 모듈:

```text
services/page_renderer.py
services/ocr.py
services/vision_captioner.py
```

추가 흐름:

```text
pdf_parser.extract_pages()
page_renderer.render_pages()
ocr.extract_text_from_page_images()
vision_captioner.caption_visual_regions()
merge_page_elements()
chunker.chunk_pages()
```

---

## 28.2 Hybrid Search 추가 시

추가 모듈:

```text
services/hybrid_retriever.py
services/fusion.py
```

검색 흐름:

```text
dense_results = pgvector search
fts_results = PostgreSQL FTS
trgm_results = pg_trgm
merged = rrf_fusion([dense_results, fts_results, trgm_results])
```

---

## 28.3 Redis/RQ 추가 시

추가 파일:

```text
workers/rq_worker.py
workers/tasks.py
```

변경 전:

```python
background_tasks.add_task(process_document, document_id)
```

변경 후:

```python
queue.enqueue(process_document, document_id)
```

`process_document(document_id)` 자체는 변경하지 않는다.

---

## 28.4 MinIO 추가 시

추가 파일:

```text
storage/minio_storage.py
```

기존 `LocalStorage`와 동일한 인터페이스를 구현한다.

---

## 28.5 Reranker 추가 시

추가 모듈:

```text
services/reranker.py
```

흐름:

```text
retrieve top 30
→ rerank
→ top 5 context
→ generation
```

---

# 29. 현재 구현 및 검증 상태

2026-08-18 기준으로 1차 MVP 기능을 구현했다. 초기 후속 범위였던 PostgreSQL
FTS, pg_trgm, RRF Hybrid 검색도 현재 구현에 포함되며, 관리자가 네 검색
알고리즘을 청킹 preset과 독립적으로 선택할 수 있다.

계정 생명주기·백업/복원과 복합 RAG 개선은 `7cb7cec`으로 커밋하고 로컬
`main`에 fast-forward 병합했다. 현재 `main`은 `origin/main`보다 3개 commit
앞서 있으며 아직 push하지 않았다.

추가로 다음 안정화 항목을 완료했다.

- 공개 회원가입과 사용자별 문서·대화 격리
- 청킹 preset 변경 시 전체 문서 재인덱싱과 API 재시작 복구
- PDF 추가·삭제와 중단된 개별 문서 인덱싱 복구
- 50MiB PDF 파일 및 multipart overhead를 포함한 51MiB 전체 request body 서버 제한
- PDF 확장자, MIME, `%PDF-` 시그니처와 PyMuPDF 구조 검증
- 손상되거나 암호화된 PDF 거절 및 부분 데이터 정리
- 격리된 PostgreSQL을 사용하는 단위·API 통합 테스트
- 실제 BGE-M3와 Gemma 4를 사용하는 PDF RAG E2E smoke 테스트
- DB, embedding, vLLM 통합 readiness와 Docker/run.sh 시작 판정 연동
- Docker 없는 서버에서 PostgreSQL, embedding, vLLM, API를 순서대로 관리하는
  native 설치·진단·시작·종료 스크립트
- PostgreSQL 17+pgvector, BGE-M3, vLLM, API를 한 이미지에서 실행하고 `/data`와
  모델 volume만 영속화하는 all-in-one 배포
- 로그인 사용자별 여러 작업공간 대화 세션 저장·조회·삭제
- 최근 대화 자동 복원, 메시지 pagination과 제한된 이전 문맥 기반 후속 질문
- 삭제된 PDF의 과거 source label 보존 및 원본 열기 비활성화
- uv 공통/API/embedding/dev dependency group 분리 및 API 이미지에서 ML/CUDA stack 제거
- 기본 관리자 제거, 명시적 bootstrap 관리자 생성과 최초 로그인 비밀번호 변경 강제
- 관리자 비밀번호 변경 시 현재 세션을 제외한 기존 로그인 세션 폐기
- 12페이지 retrieval 평가 fixture와 5 preset x 4 알고리즘 Recall@5·MRR·latency benchmark
- 격리된 tmpfs DB와 실제 BGE-M3를 사용하는 benchmark 자동 실행 스크립트
- Keyword FTS 질문 토큰 OR-query와 전 preset Recall@5 `1.0` 검증
- 직전 질문·답변 한 쌍을 사용하는 후속 질문 retrieval query rewriting
- SSE 기반 답변 스트리밍, 완료된 대화만 저장하고 실패한 빈 세션 정리
- 스트리밍 중 `NO_SOURCE` 마커 비노출과 자료 부재 시 빈 source 유지
- JSON 구조화 로그, `X-Request-ID`와 Prometheus HTTP·retrieval·LLM 지표
- 실제 Gemma 4 SSE delta·출처·완료와 관측 지표 E2E 검증
- 답변의 `Source N` 인용만 실제 문서·페이지 source로 반환하고 검색 후보 전체 노출 방지
- 간호 특화 prompt를 범용 문서 RAG prompt로 교체하고 system/user/history 역할별
  메시지 구성을 분리
- 일반 사용자 비밀번호 변경 UI와 다른 로그인 세션 폐기
- 비밀번호·사용자명 재확인 후 계정 소유 문서·대화·PDF 원본 회원탈퇴
- Docker/native PostgreSQL dump와 uploads, manifest, SHA-256을 묶는 백업·복원 스크립트
- 복합 질문은 고유 `goal_id`가 있는 최대 4개 원자적 근거 목표와 goal별 검색어로
  계획하고 RRF, 인접 chunk와 BGE-M3 재정렬을 적용
- goal별 최상위 후보를 보존하고 `supported`/`partial`/`missing`/`contradicted`
  상태와 검증된 Source/Page/chunk를 trace에 저장
- unresolved goal 표적 검색과 page FTS·trigram 계층 fallback 최대 2회, 빈 재검색 시 Context 보존
- 문장별 Source/Page 검증, 조건부 인용 보정과 SSE `revision`
- 7개 복합 Git/라이선스 fixture의 balanced+hybrid Recall@3·MRR@3 `1.0`
- 빠른 단위/API 통합 테스트 `207 passed`, 실제 모델 E2E `1 skipped`
- 최초 Context를 비운 실제 Gemma 4 강제 테스트에서 최대 2회 검색과 유효 인용 확인
- API·DB·embedding·LLM 4개 컨테이너 및 `/health/ready` 정상 확인
- `sample/`의 3개 문서군을 위한 복합·다층 추론 10개 fixture와 격리 benchmark runner
- text-only page 감사, `parse/retrieval/reasoning/citation/calibration` 실패 분류 절차
- 19개 PDF 696페이지 1차 실측: 복합 추론 10개 중 pass 3, partial 4, fail 3
- 시각 전용 페이지 환각 2건, 설계 지연 감점 retrieval 실패 1건을 개선 기준선으로 확보
- 좌표 기반 block 추출, 반복 머리말·꼬리말/페이지 번호 제거, 표 구조와 페이지별
  언어·시각 근거 위험 metadata 저장
- 화면 전사·다이어그램 계산 질문의 text-only 사전 차단, 교차언어 검색,
  evidence matrix 부분 답변과 재검색 Context 보존 적용
- 최종 실제 모델 10건 잠정 수동 평가 `pass 7 / partial 2 / fail 1`; 시각 전용
  2건은 안전 거부, 영문 지연 감점은 recall 1.0 및 정량/정성 구분 답변으로 개선
- Gemma 4 W4A16의 실제 PDF 페이지 이미지 입력과 화면 문자열 판독 성공
- vLLM 양자화 vision projection dtype 호환성 보완 및 요청당 이미지 1개 제한 적용
- `risk_only`/`all_visual` 선택 페이지의 144 DPI 렌더링과 구조화 Vision caption 적용
- page metadata에 caption 상태·버전·모델·confidence를 저장하고 원문과 분리된
  `vision_caption` chunk를 BGE-M3로 임베딩해 기존 네 검색 알고리즘에 통합
- 실제 Manual 19페이지에서 `LB05 01 NLNNN` 추출과 text/vision chunk 생성 확인
- query plan·근거 충족도 JSON 출력을 강제하고 복구 시 직전 대화 문맥을 유지하며,
  절차 질문의 표준 명령어 검색 확장과 chunk metadata 기반 Source/Page 정규화 적용
- 모든 근거 목표가 부족한 모호 질의는 LLM 초안을 스트리밍하지 않고 구체화를 요청하며,
  citation repair의 전면 거부 시에는 유효하게 인용된 문장만 보존하는 fallback 적용
- 관리자 지원 임시 비밀번호 재설정, 대상 사용자 전체 세션 폐기와 다음 로그인 변경 강제
- 여러 OpenAI 호환 LLM endpoint 등록, 기본 endpoint key 선택과 Vision capability 검증
- 통합 문서군의 RS485, SRUP, stash 선행 조건, MPL/GPL 해결책, 모호 rollback을
  각 3회 집중 회귀하고, 답변 가능 사례 최종 recall `1.0`과 안전 구체화 요청 확인
- backtick 리터럴의 문자·위치별 감사와 Context 기반 채널 의미 정규화로
  `NLNNB` 해석, CR(0x0d), 50ms 조건을 최종 3/3 보존
- Gemma 4 JSON mode의 손상된 query plan field를 의미 보존 범위에서 정규화해 실제
  reasoning fixture planner 응답 11/11을 goal plan으로 복구
- 근거 충족도 repair가 알 수 없는 goal/chunk ID를 반환하면 잘못 연결하지 않고
  `unchecked` matrix로 fallback하며, 최대 2회 bounded retrieval을 유지
- visual-only 실패 경계 2개는 각각 3/3 거부·빈 source, 3일 지연 정량 사례는
  `-5% × 3 = -15%`와 모델 불일치 정량 한계를 최종 3/3 보존
- 8,192-token model에 8,243-token 복합 prompt가 전달돼 SSE 400이 발생하는 문제를
  Evidence Matrix와 서로 다른 page를 우선하는 14,000자 생성 Context로 제한하고,
  endpoint의 context/output 합계 초과에는 output budget을 한 번만 줄여 재시도
- 실제 `1512.03385v1.pdf` 4개 goal 질문에서 오류를 재현한 뒤 수정 경로가
  `session`, 다중 `delta`, `revision`, `sources`, `done` event를 완료함을 확인
- `run_aio.sh`로 원샷 이미지 build/pull/up/readiness/status/logs/down 경로를 통합하고,
  실제 Web UI 회원가입·Manual 업로드·인덱싱·Gemma 답변과 page source를 확인
- all-in-one image에서 Gemma 4 weight를 제거하고 12B·31B W4A16 archive를 외부
  storage에서 이어받아 SHA-256 검증 후 `/data/models/gemma4`에 원자적으로 설치
- 설치된 모델을 `/data`에서 재사용하고 기본적으로 검증 완료 archive를 삭제해
  Docker Hub pull과 재시작 비용을 분리
- 공개 Hugging Face repository의 commit SHA로 고정한 모델 snapshot 이어받기·설치·재사용
- `chown`이 제한된 volume의 실제 UID로 PostgreSQL을 실행하는 fallback을 12B·31B
  `0.1.4` image에 공통 적용하고 image별 실제 downloader·권한 smoke 검증
- H200 단일 GPU용 BGE-M3 CUDA, vLLM sequence 8개 31B 배포 설정 유지;
  이번 변경에서는 31B 기동·추론 미실시
- `LLM_ENDPOINTS_FILE` JSON을 endpoint 허용 목록으로 사용하고 모든 로그인 사용자가
  작업공간에서 자신의 언어모델을 검증·전환하며 DB에 보존해 세 실행 방식에 공통 적용

빠른 테스트는 `./scripts/test.sh -q`, 실제 모델 E2E는 네 서비스 실행 후
`./scripts/e2e.sh -q`로 수행한다. E2E API와 DB는 운영 데이터와 분리된다.
