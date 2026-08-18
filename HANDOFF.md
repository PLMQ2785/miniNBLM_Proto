# miniNBLM 개발 핸드오프

## 1. 현재 상태

- 기준일: 2026-08-11 (Asia/Seoul)
- 프로젝트: 사용자 PDF 기반 범용 RAG Assistant
- 현재 단계: 1차 MVP, Vision caption, native 실행과 원샷 통합 이미지 지원 완료
- 패키지 관리: `uv`
- 런타임: 4-container Compose, 단일 all-in-one container, 또는 `run-native.sh`
- Web UI: React 없이 FastAPI가 Vanilla HTML/CSS/JavaScript 정적 파일 제공
- PostgreSQL 기본 포트는 다른 로컬 DB와 충돌하지 않도록 5433을 사용

최근 검증 결과:

- 빠른 단위/API 통합 테스트: `202 passed`, 실제 모델 E2E `1 skipped`
- 실제 BGE-M3/Gemma 4 E2E: `1 passed`
- 실제 Gemma 4 SSE에서 다중 delta, 출처, 완료 event와 대화 저장 확인
- JSON 구조화 로그, `X-Request-ID`, Prometheus HTTP·검색·LLM 지표 확인
- 자료 밖 질문 E2E에서 거부 응답의 source가 빈 배열인지 확인
- 실제 `GET /health/ready`: DB, embedding, LLM 모두 `ok`, HTTP 200
- native API·BGE-M3 process와 외부 PostgreSQL·vLLM 조합에서 `/health/ready`
  3개 component `ok`, foreground 종료 시 native process 역순 정리 확인
- Docker/native 백업 생성, checksum 검증, 동일 bundle 복원 smoke 통과
- all-in-one 이미지에서 PostgreSQL·embedding·vLLM·API 4개 process 실행,
  `/health/ready` 3개 component `ok`, 내부 백업·checksum·실제 복원과 exit 0 종료 확인
- 12B·31B all-in-one image에서 모델 weight를 제거하고 외부 archive 또는 commit
  SHA로 고정한 공개 Hugging Face snapshot을 `/data/models/gemma4`에 검증 후
  원자적으로 설치·재사용하는 경로로 전환
- 12B archive SHA-256, HF snapshot, 잘못된 checksum 거부, 불완전 설치 방지와 cache 재사용 확인
- `run_aio.sh --no-build` 실제 기동, status·down·재기동, 기본 비밀번호 거부 확인
- `chown`이 제한된 RunPod Network Volume의 실제 UID로 PostgreSQL을 실행하고
  DB·embedding·LLM readiness가 모두 `ok`인 startup smoke 확인
- 원샷 Web UI에서 회원가입, Manual 19페이지 업로드·인덱싱, 실제 Gemma 답변과
  5·18페이지 source 표시 확인
- Gemma 4 31B 직접 양자화 W4A16 checkpoint와
  `cpsu/mininblm:0.1.3-gemma4-31b-w4a16` 배포 image 추가
- 31B image에도 Hugging Face snapshot downloader와 제한된 volume UID fallback을
  적용하고 실제 snapshot·권한 smoke 및 runtime 계약을 검증
- H200 1장 기준 BGE-M3 CUDA, vLLM GPU memory `0.70`, 활성 sequence `8`,
  tensor parallel `1`로 31B 배포 profile 갱신 및 image build 성공
- 31B H200 실제 readiness와 생성 요청은 원격 검증 대상으로 남음
- API 이미지: `6,555,721,208` bytes에서 `206,676,250` bytes로 약 96.8% 감소
- API 이미지의 Torch/Sentence Transformers/Transformers 제거 및 embedding 이미지의
  Torch/Sentence Transformers 유지 확인
- Playwright FE 사용성 smoke: 문서 refresh 실패/복구, 질문 실패/재시도,
  답변·오류 focus, 390px 모바일 overflow 검증 통과
- 최신 Playwright 확인: 로그인 후 문서 선택 없이 전체 작업공간 질문 가능,
  source 문서명 표시, `전체 문서 검색` 제목과 질문 입력 placeholder 제거 확인
- 대화 세션 Playwright 확인: 생성, 후속 질문 session 재사용, 새로고침 자동
  복원, 새 대화, 전환·삭제와 390px 반응형 배치 통과
- 다중 PDF 업로드 controller smoke: 선택한 2개 파일의 순차 요청, 문서 목록 반영,
  완료 알림 검증 통과
- 실제 제공 HTML에서 PDF input의 `multiple` 속성 반영 확인
- 최신 정적 검사: 전체 Vanilla JS `node --check`, `git diff --check` 통과
- E2E 및 일반 테스트용 임시 컨테이너는 테스트 종료 후 정리됨
- 기본 관리자 계정 제거, 명시적 bootstrap과 최초 로그인 비밀번호 변경 강제,
  다른 로그인 세션 폐기 검증 완료
- 12페이지/8질문 fixture로 5 preset x 4 알고리즘 Recall@5·MRR·latency matrix 완료
- Keyword OR-query 개선 후 실측 Recall@5: 전 preset `1.0` (기존 `0.125`)
- 후속 질문 retrieval query rewriting 단위/API 통합 테스트 완료
- 일반 사용자 비밀번호 변경과 다른 로그인 세션 폐기 API/UI 적용
- 비밀번호·사용자명 재확인 회원탈퇴와 문서·대화·PDF 원본 일괄 삭제 적용
- 관리자 지원 임시 비밀번호 재설정, 대상 사용자 전체 세션 폐기와 다음 로그인 변경 강제
- OpenAI 호환 모델 endpoint 목록과 기본 endpoint key를 분리해 여러 주소 선택 기반 마련
- DB dump와 uploads, manifest, SHA-256을 묶는 백업 bundle 생성·검증 완료
- Playwright 계정 smoke: 일반 사용자 비밀번호 변경, 390px overflow 없음,
  회원탈퇴 후 세션·재로그인 차단 확인
- 복합 Git 질의에서 최대 4개 근거 질의와 최대 2개 교차언어 질의, RRF, 인접 chunk, BGE-M3 semantic
  reranker와 근거 충족도 기반 제한 재검색(표적 chunk + page 계층, 최대 2회) 확인
- 실제 Gemma 4에서 reset·revert·DVCS 근거를 여러 PDF 페이지에서 결합하고,
  답변에 인용된 5개 문서 페이지만 source로 반환하는 경로 확인
- 주장별 인용 검증 적용 후 동일 복합 질의의 모든 실질 문장에 유효한
  Source/Page가 붙고 실제 인용된 4개 페이지만 source로 반환되는 경로 확인
- 장문·간접 표현을 포함한 7개 복합 fixture에서 balanced+hybrid Recall@3,
  Hit@3, MRR@3 모두 `1.000` 확인
- 최초 Context를 비운 실제 Gemma 강제 테스트에서 page 계층 fallback과 표적
  검색이 정확히 2회 내 종료되고 reset·revert·DVCS 결합 답변 생성 확인
- 실제 `sample/` 19개 PDF, 696페이지의 text-only 감사와 문서군별 복합 추론
  10개 기준선 완료: pass 3, partial 4, fail 3
- 시각 전용 2개 사례에서 정답 페이지는 검색했지만 화면 근거가 없어 잘못된 값을
  생성했고, 설계 지연 감점 사례는 source recall 0으로 retrieval 실패 확인
- 설계 지연 감점 실패 trace에서 영문 정답 문서에 대한 검색 계획이 한국어 질의만
  생성되어 hybrid와 page 후보가 한국어 문서에 편향된 교차언어 retrieval gap 확인
- 좌표 기반 PDF block 순서, 반복 머리말·꼬리말/페이지 번호 제거, 표 구조 보존과
  페이지별 언어·image/drawing·시각 근거 위험 메타데이터를 chunk까지 전달
- 페이지를 지정한 화면 전사·다이어그램 계산 질문은 시각 근거가 있으면 LLM 호출 전에
  text-only 한계 답변으로 종료하고 source를 반환하지 않음
- 교차언어 검색어 1~2개, query plan 형식 복구 1회, 검색 방식/질의별 후보 보존,
  재검색 시 최초 Context 우선 보존과 근거 매트릭스 기반 부분 답변 적용
- embedding query 5개 batch 계약 준수, 생성 토큰 제한·반복 퇴행 감지 후 1회 재생성,
  불완전한 Source/Page 구조 보정 적용
- 2026-08-07 10개 기준선(`20260807T060016Z`)은 source recall 8건 `1.0`,
  2건 `0.75/0.667`, 잠정 수동 평가 `pass 7 / partial 2 / fail 1`이었다.
- 2026-08-10 집중 회귀(`20260810T040614Z`)에서 RS485, SRUP, stash 선행 조건,
  MPL/GPL 해결책, 모호 rollback을 각 3회 검증했다. 답변 가능 12회는 최종 recall
  `1.0`, 모호 rollback 3회는 source 없는 구체화 요청으로 종료했다. MPL/GPL 해결
  선택지도 3/3 모두 포함했다.
- RS485 리터럴·위치 의미를 Context의 채널 정의로 결정적으로 정규화한 최종
  3회 실행(`20260810T042126Z`)은 `NLNNB`, Normal/Leak/Normal/Normal/Broken,
  CR(0x0d), 50ms를 3/3 모두 보존했다.
- Gemma 4 W4A16의 실제 `image_url` 입력으로 PDF 화면 문자열
  `LB05-01 NLNNN`을 정확히 읽고, 직후 텍스트 요청과 네 컨테이너 정상 상태 확인
- 양자화 projection에서 vLLM 0.25.0이 `weight.dtype`를 조회해 종료되던 문제를
  custom LLM 이미지의 `params_dtype` 보완으로 해결하고 이미지 입력을 요청당 1개로 제한
- 선택된 페이지를 144 DPI PNG로 렌더링하고 Gemma 4 구조화 caption을 page metadata와
  별도 `vision_caption` chunk로 저장해 기존 BGE-M3 검색에 통합
- 실제 Manual 19페이지 전체 경로에서 `LB05 01 NLNNN` 구조화 추출,
  `text`와 `vision_caption` 두 검색 chunk 생성 확인
- 복잡한 상태 다이어그램은 형식 실패와 OCR·관계 모순이 반복되어 운영 기본값을
  `disabled`로 유지하고, JSON Schema 강제 및 명시적 `risk_only` 실험 모드로 제한
- query plan과 evidence coverage 출력에 JSON object 형식을 강제하고, 형식 복구에도
  직전 질문·답변을 전달해 후속 질문이 원문 한 줄 검색으로 퇴행하지 않도록 보완
- 기능 브랜치 작업 중 Hotfix 전환 후 복원하는 후속 질문에서 `git stash` 검색어와
  Version management II 13페이지, Branch 20페이지를 함께 회수하고 답변 생성 확인
- Source 번호가 유효하지만 모델이 Page 번호를 잘못 쓴 경우 chunk의 실제 page metadata로
  결정적으로 정규화해 UI source 목록과 본문 인용이 일치하도록 보완
- 답변 delta 종료 후 조건부 citation validation LLM과 DB 저장이 끝나야 source/done SSE를
  전송한다. 재시작 후 실측 citation validation 1회는 7.36초였으며 현재 동작을 유지
- citation repair가 `NO_SOURCE`를 반환해도 초안의 유효한 Source/Page 인용 문장은
  보존하고 인용 없는 주장은 제거하며, 모든 근거 목표가 부족하면 LLM 초안을 스트리밍하지
  않고 수행 작업·오류·현재 상태를 구체화해 달라는 단일 응답으로 종료
- 실제 commit rollback 모호 질의에서 `revision` 없이 구체화 요청 1회, 빈 source를
  반환하는 경로를 확인하고 잘못된 `[Source 1, Page 5, 4, ...]` 목록도 무효 처리

최근 작업:

| Commit | 내용 |
|---|---|
| `ece7d7e` | text-only grounding, 교차언어 검색, 복합 추론 평가와 Vision 런타임 호환성 |
| `7cb7cec` | 계정 생명주기·백업/복원과 복합 RAG 제한 재검색·계층 fallback·trace 통합 |
| `158c952` | 답변 스트리밍, 관측성 및 범용 RAG prompt 적용 |
| `2a8afe6` | 복합 retrieval과 후속 질문 검색 개선 |
| `e49d13b` | 사용자 소유의 모든 indexed 문서를 검색하도록 API/검색 쿼리 전환 |
| `39ef1e7` | RAG source에 문서 제목을 포함하고 UI/PDF panel에 표시 |
| `2b1f005` | 채팅 요청과 UI에서 문서 선택 개념 제거 |
| `13c88fb` | 검색 제목과 질문 입력 placeholder 제거 |
| `be00453` | 사용자별 작업공간 대화 세션, 메시지 이력 및 후속 질문 문맥 저장 |
| `6f5b97e` | 자료에서 답을 찾지 못한 거부 응답의 source 제거 |
| `dd1a8c5` | 여러 PDF 동시 선택, 순차 업로드 및 부분 실패 처리 |

## 2. 시스템 구성

```text
Browser
  -> api:8080
       -> db:5433             PostgreSQL 17 + pgvector
       -> embedding:8070      BAAI/bge-m3
       -> llm:8010            vLLM + Gemma 4 12B W4A16
```

| 서비스 | 주소 | 역할 | GPU |
|---|---|---|---|
| `api` | `0.0.0.0:8080` | FastAPI, Web UI, 문서 처리 조정 | 아니요 |
| `db` | `127.0.0.1:5433` | PostgreSQL 17, pgvector | 아니요 |
| `embedding` | `127.0.0.1:8070` | BGE-M3 embedding HTTP API | 예 |
| `llm` | `127.0.0.1:8010` | vLLM OpenAI-compatible API | 예 |

배포 단위를 줄여야 할 때는 `Dockerfile.all-in-one`이 네 논리 서비스를 컨테이너
하나의 process로 실행한다. 모델 없는 runtime image를 pull한 뒤 외부 archive를
검증하여 `/data/models/gemma4`에 설치한다. PostgreSQL·uploads·모델·cache·로그는
`/data`에 보존되어 image 교체와 재시작에서 재사용된다.

WSL mirrored networking에서 Docker bridge port가 Windows localhost로 전달되지
않는 문제가 있어 모든 런타임 서비스가 `network_mode: host`를 사용한다. API만
외부에 bind하고 DB, embedding, LLM은 loopback에만 bind한다.

## 3. 모델 및 GPU 설정

- Embedding model: `BAAI/bge-m3`
- Embedding dimension: `1024`
- LLM: Gemma 4 12B instruction model, W4A16 compressed-tensors 양자화
- 기본 모델 경로: `./google/gemma-4-12B-it-W4A16`
- vLLM Docker/native version: `0.25.0`
- 기본 max model length: `8192`
- 기본 GPU memory utilization: `0.65`
- 기본 max sequences: `4`
- readiness 구성요소별 timeout: `3초`

`Dockerfile.llm`과 native 환경은 vLLM `0.25.0`으로 고정하고 Gemma 4 unified
quantization patch를 적용한다. `latest` 재빌드에서 model config 호환성 오류가
확인되어 floating base image를 사용하지 않는다. WSL에서 Model Runner V2의 UVA를
사용하기 위해 `VLLM_WSL2_ENABLE_PIN_MEMORY=1`과 `ipc: host`가 필요하다. vLLM
또는 모델 구조를 변경하면 실제 completion E2E를 반드시 다시 실행한다.

## 4. 구현 완료 기능

### 인증 및 사용자 격리

- 공개 회원가입, 로그인, 로그아웃, 현재 사용자 조회
- Argon2id 비밀번호 해시
- 원문을 저장하지 않는 SHA-256 세션 토큰 해시
- `HttpOnly`, `SameSite=Lax` 세션 쿠키
- 사용자별 문서, PDF 원본, 질문, 대화 및 삭제 접근 격리
- 다른 사용자의 문서 ID 접근 시 HTTP 404
- `admin` 역할과 관리자 CLI
- 기본 관리자 없음, 두 bootstrap 환경변수를 명시한 경우에만 최초 관리자 생성
- bootstrap/CLI 승격 관리자의 최초 로그인 비밀번호 변경 강제
- 비밀번호 변경 전 문서·채팅·관리 API 차단 및 다른 로그인 세션 폐기
- 일반 사용자 계정 화면에서 비밀번호 변경
- 회원탈퇴 시 인증 세션, 문서/page/chunk, 대화와 PDF 원본 hard delete
- 관리자 화면에서 일반 사용자 임시 비밀번호 재설정과 전체 세션 폐기
- 재인덱싱 감사 이력은 요청자만 `NULL`로 전환해 보존

### PDF 문서 처리

- PDF 업로드, 목록, 상태 조회, 원본 inline 조회, 삭제
- PyMuPDF page 단위 텍스트 추출
- 문자 수 기반 page 단위 chunking
- BGE-M3 embedding 생성 및 pgvector 저장
- 문서 상태: `uploaded`, `processing`, `indexed`, `failed`
- 처리 중 문서 삭제 시 HTTP 409
- API 재시작 시 중단된 `uploaded/processing` 문서 자동 복구
- 원본 파일이 사라진 중단 문서는 원인을 기록하고 `failed` 처리

업로드 검증:

- 기본 50MB 서버 파일 제한 (`MAX_UPLOAD_BYTES=52428800`)
- `.pdf` 파일명과 PDF MIME type 요구
- `%PDF-` 시그니처 검사
- PyMuPDF를 이용한 PDF 구조 및 page 존재 검사
- 손상된 PDF와 암호화된 PDF는 HTTP 400
- 용량 초과는 HTTP 413
- 거절된 업로드의 DB 행과 부분 파일 자동 정리
- 텍스트가 없는 정상 PDF는 업로드 후 인덱싱 단계에서 `failed`

### 검색 및 답변

- 로그인 사용자의 모든 `indexed` 문서에 대한 작업공간 단위 질문
- Dense/Keyword/Substring/Hybrid 쿼리에서 `documents.owner_id` 직접 JOIN 검증
- `/chat` 요청은 `question`과 선택적 `session_id`만 받고 문서 선택값을 사용하지 않음
- 작업공간 chat session은 특정 문서에 귀속하지 않고 `document_id=NULL`로 저장
- 사용자별 여러 대화 세션, 최근 활동순 목록, 메시지 pagination과 삭제
- 로그인·새로고침 시 최근 대화 자동 복원
- 후속 질문 생성에 최근 8개 메시지를 최대 8,000자까지 전달
- 후속 질문 검색에는 직전 사용자 질문 500자와 답변 1,000자까지만 사용해
  독립형 retrieval query를 생성하며, 최종 답변과 저장에는 원문 질문을 유지
- 복합 질문은 최대 4개 근거 검색어와 최대 2개 반대 언어 검색어로 계획하고 RRF로 병합
- Dense/Hybrid 후보는 원질문·세부 질의 BGE-M3 유사도와 기존 순위로 재정렬하며
  질의별 최상위 검색·의미 후보를 보존
- 검색 근거 충족도를 LLM으로 검사하고 부족한 전제는 표적 chunk 검색과 page
  FTS·trigram 계층 fallback으로 최대 2회 재검색한다. 빈 재검색은 기존 Context를
  보존하고 최종 판정이 불안정해도 병합 근거를 답변 모델에 전달한다.
- 계층 fallback은 세부 질의별 상위 페이지를 보존하고 해당 페이지와 겹치는
  chunk만 BGE-M3로 재정렬한다.
- 삭제된 PDF의 과거 source 제목은 보존하고 원본 접근은 비활성화
- 자료에서 답을 확인할 수 없다는 응답은 source를 반환하지 않으며, 모델이
  `[[NO_SOURCE]`처럼 마커 대괄호를 일부 누락해도 후처리함
- Gemma 4/vLLM 답변 생성
- SSE 답변 스트리밍, 완료 후 대화 이력 저장과 실패한 신규 세션 정리
- 스트리밍 중 `NO_SOURCE` 판정 전 초기 출력 버퍼링과 marker 비노출
- retrieval top-k 전체가 아니라 답변의 유효한 `Source N` 인용만 source로 반환
- 인용 누락·잘못된 Source/Page가 있는 답변만 LLM 보정 1회 수행
- SSE 보정 결과는 `revision` event로 화면을 교체하고 보정본만 DB에 저장
- 동일 문서·페이지 인용 중복 제거, 미인용 후보와 잘못된 번호 제외
- 기존 대화의 후보 source metadata도 조회 시 인용 번호로 동적 필터링
- 간호 특화 시스템 프롬프트를 범용 문서 RAG 정책으로 교체하고 prompt builder를
  `build_system_message`, `build_user_message`, `build_rag_messages` 역할별 함수로 분리
- source document ID/title/page/chunk 반환
- PDF source page 열기
- 자료 밖 질문 제한, 추측 금지와 정확한 Source/Page 인용을 포함한 범용 system prompt

검색 알고리즘 4개:

| Key | 구현 |
|---|---|
| `dense` | BGE-M3 + pgvector cosine/HNSW |
| `keyword` | PostgreSQL FTS, `simple` config, 질문 토큰 OR query |
| `substring` | pg_trgm similarity |
| `hybrid` | Dense + FTS + pg_trgm 결과의 RRF |

### 관리자 검색 설정

- built-in 청킹 preset 5개
- 검색 알고리즘 4개 독립 선택
- 알고리즘 변경은 재인덱싱 없이 즉시 적용
- 청크 크기/오버랩 변경은 전체 문서 재청킹 및 재임베딩
- `LLM_ENDPOINTS_FILE` JSON 허용 목록 중 모든 로그인 사용자가 자신의 언어모델을
  즉시 전환하며 사용자별 선택값을 DB에 보존
- endpoint 등록정보는 운영자가 JSON으로 수동 관리하고 변경 후 API를 재시작
- 전환 전 OpenAI 호환 `/models`와 model ID를 검증하고 답변·caption에 공통 적용
- 재인덱싱 중 질문과 문서 변경을 유지보수 모드로 차단
- 작업 상태 및 진행률 조회
- 실패 작업 재시도 API
- API 재시작 시 중단된 전체 재인덱싱을 처음부터 자동 복구
- 기존 사용자, 세션, 원본 PDF는 보존

초기 preset은 다음과 같다.

| Key | chunk size | overlap | top-k |
|---|---:|---:|---:|
| `fine_grained` | 200 | 40 | 20 |
| `standard` | 500 | 75 | 12 |
| `balanced` | 1000 | 150 | 8 |
| `broad_context` | 2000 | 300 | 5 |
| `long_form` | 3500 | 500 | 4 |

### Web UI

- 반응형 데스크톱/모바일 작업공간
- 회원가입 및 로그인 화면
- 여러 PDF 동시 선택, 순차 업로드, 부분 실패 재시도, 상태 polling 및 삭제 관리 목록
- indexed 문서가 하나 이상이면 선택 없이 활성화되는 작업공간 질문창
- DB에 저장되는 여러 작업공간 대화와 최근 대화 자동 복원
- 대화 선택, 새 대화, 삭제와 이전 메시지 페이지 불러오기
- 질문과 답변, source page 선택
- 답변 출처를 `문서명 · 페이지`로 표시하고 해당 문서 PDF panel 제목에 연동
- 모바일 문서 drawer 및 PDF source panel
- 관리자 preset/알고리즘 화면과 재인덱싱 상태 polling
- 문서 목록 수동 새로고침과 목록 로드 실패 인라인 재시도
- 실패한 질문의 대화 내 재시도와 업로드·삭제 실패 알림 액션
- 새 답변 및 직접 작업 오류로 keyboard focus 이동
- 자동 polling 오류는 사용자 입력 focus를 유지
- 모델 출력은 HTML로 해석하지 않고 text로 렌더링
- 답변 delta를 수신하는 즉시 같은 message 영역에 표시하고 완료 후 source 연결

### 관측성

- 모든 API 응답의 `X-Request-ID` 생성·전파
- stdout JSON 구조화 로그와 method, route, status, 전체 응답 지연 기록
- Prometheus HTTP 요청 수·지연, retrieval·rerank·근거 충족도·재검색,
  인용 검증, LLM 결과·지연·TTFT 지표
- assistant metadata와 JSON 로그에 request별 retrieval trace 저장
- 관리자 전용 `GET /admin/retrieval/traces` 최신 trace 조회
- 스트림 success/error/cancelled 결과 지표
- `/metrics` 공개 endpoint 제공, 운영 reverse proxy에서 모니터링망 제한 필요

## 5. 주요 API

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/health` | API 프로세스 liveness |
| `GET` | `/health/ready` | DB, embedding, vLLM 통합 readiness |
| `GET` | `/metrics` | Prometheus 형식 관측 지표 |
| `POST` | `/auth/register` | 회원가입과 세션 발급 |
| `POST` | `/auth/login` | 로그인 |
| `POST` | `/auth/logout` | 세션 폐기 |
| `POST` | `/auth/password` | 현재 비밀번호 검증 및 안전한 비밀번호 변경 |
| `DELETE` | `/auth/account` | 비밀번호·사용자명 재확인 후 계정과 소유 데이터 삭제 |
| `GET` | `/auth/me` | 현재 사용자 |
| `POST` | `/documents` | PDF 업로드 |
| `GET` | `/documents` | 현재 사용자 문서 목록 |
| `GET` | `/documents/{id}` | 문서 처리 상태 |
| `GET` | `/documents/{id}/file` | 원본 PDF inline 응답 |
| `DELETE` | `/documents/{id}` | 문서 및 관련 데이터 삭제 |
| `POST` | `/chat` | 전체 indexed 문서 질문 및 세션 생성/후속 메시지 |
| `POST` | `/chat/stream` | SSE 답변 delta, source와 완료 event |
| `GET` | `/chat/sessions` | 현재 사용자의 최근 대화 목록 |
| `GET` | `/chat/sessions/{id}` | 대화 메시지/source 페이지 조회 |
| `DELETE` | `/chat/sessions/{id}` | 현재 사용자 소유 대화 삭제 |
| `GET` | `/admin/retrieval` | 관리자 검색 설정 상태 |
| `GET` | `/admin/retrieval/traces` | 최근 답변 retrieval trace 조회 |
| `POST` | `/admin/retrieval/presets/{key}/activate` | preset 변경/재인덱싱 |
| `POST` | `/admin/retrieval/algorithms/{key}/activate` | 알고리즘 즉시 변경 |
| `GET` | `/language-models` | 로그인 사용자의 등록 언어모델과 선택 조회 |
| `POST` | `/language-models/{key}/activate` | endpoint 검증 후 사용자별 언어모델 전환 |
| `GET` | `/admin/retrieval/jobs/{id}` | 재인덱싱 작업 조회 |
| `POST` | `/admin/retrieval/jobs/{id}/retry` | 실패 작업 재시도 |

`/health`는 외부 의존성과 무관한 liveness를 제공한다. `/health/ready`는 DB
`SELECT 1`, embedding `/health`, vLLM `/v1/models`를 병렬 확인하고 구성요소별
상태와 지연 시간을 반환한다. 하나라도 실패하면 HTTP 503을 반환한다.

## 6. 실행 방법

최초 또는 이미지 재빌드가 필요한 실행:

```bash
cp .env.example .env   # .env가 없을 때만
./run.sh
```

이미지가 준비된 이후 빠른 실행:

```bash
./run.sh --no-build
```

관리 명령:

```bash
./run.sh status
./run.sh logs
./down.sh
```

접속 주소:

- WSL/Linux/Windows host: `http://localhost:8080/`
- mirrored WSL에서 LAN: `http://<Windows_HOST_IP>:8080/`

Windows Host IP는 PowerShell의 `ipconfig`에서 실제 Wi-Fi/Ethernet adapter의
IPv4 주소를 사용한다.

기존 일반 계정의 관리자 권한 변경:

```bash
docker compose exec api python -m app.cli.set_admin <username>
docker compose exec api python -m app.cli.set_admin --revoke <username>
```

기본 관리자 계정은 없다. 최초 관리자가 필요하면 `.env`의
`BOOTSTRAP_ADMIN_USERNAME`과 `BOOTSTRAP_ADMIN_PASSWORD`를 함께 설정한다.
임시 비밀번호는 8자 이상, 영문 대·소문자·숫자·기호 중 3종 이상이어야 하며
사용자명을 포함할 수 없다. 최초 로그인 또는 CLI 승격 후 Web UI에서 새
비밀번호로 변경해야 작업공간과 관리자 API를 사용할 수 있다.

## 7. 테스트

### 빠른 단위/API 통합 테스트

```bash
./scripts/test.sh -q
```

- `docker-compose.test.yml` 사용
- 임시 PostgreSQL/pgvector: `127.0.0.1:55432`
- DB: `rag_test_db`, tmpfs
- 운영 DB, 업로드 파일, GPU, embedding, LLM을 사용하지 않음
- embedding과 LLM 호출은 test double로 대체
- 테스트 종료 시 컨테이너 자동 정리
- 운영 DB 오접속을 막는 `MININBLM_TEST_DATABASE=1` 안전장치 존재
- 마지막 결과: `94 passed`, 실제 모델 E2E `1 skipped`

단위 테스트만 실행:

```bash
uv run pytest tests/unit -q
```

### 실제 모델 E2E

먼저 운영 `embedding:8070`, `llm:8010`이 실행 중이어야 한다.

```bash
./scripts/e2e.sh -q
```

- `docker-compose.e2e.yml` 사용
- 전용 API: `127.0.0.1:18080`
- 전용 PostgreSQL: `127.0.0.1:55433`, tmpfs
- 실제 BGE-M3와 Gemma 4만 운영 endpoint를 공유
- pytest는 E2E API 컨테이너 안에서 실행해 WSL host-network 전달과 분리
- fixture: `sample_fall_prevention.pdf` 4페이지
- 1024차원 embedding 저장, SSE 다중 delta·완료, 정답/source page, 자료 밖 질문과
  관측 metric 검증
- 테스트 종료 시 전용 API, DB 및 업로드 데이터 자동 정리
- 마지막 결과: `1 passed`

### Retrieval 품질 benchmark

```bash
./scripts/benchmark-retrieval.sh
```

- 전용 tmpfs PostgreSQL과 API dependency 기반 runner 사용
- 운영 BGE-M3만 공유하고 운영 DB/업로드/LLM은 사용하지 않음
- 정답 PDF 4페이지 + 혼동 PDF 8페이지, 평가 질문 8개
- 5 preset x Dense/Keyword/Substring/Hybrid 20개 조합
- warmup 1회, 질문별 3회, Recall@5·Hit rate@5·MRR@5·p50/p95 측정 완료
- 결과는 `benchmark_results/retrieval/`에 저장되며 Git에서 제외
- Keyword 질문 토큰 OR-query 적용 후 전 preset Recall@5 `1.0`, MRR `0.854~0.938`

PyMuPDF SWIG 타입에서 발생하는 5개의 deprecation warning은 현재 알려진
비차단 경고다.

## 8. DB 및 데이터 보존

Alembic migration:

1. `0001_initial_schema.py`
2. `0002_user_auth_and_ownership.py`
3. `0003_retrieval_presets.py`
4. `0004_search_algorithms.py`
5. `0005_chat_session_history.py`
6. `0006_admin_password_change.py`
7. `0007_account_deletion.py`

영속 데이터:

- PostgreSQL: Docker volume `postgres_data`
- 업로드 PDF: 호스트 `./data`, 컨테이너 `/app/data`
- Hugging Face cache: Docker volume `hf_cache`
- 양자화 모델: 호스트 경로를 `/models/gemma4:ro`로 mount
- native 실행: `.native/postgres`, `.native/huggingface`, `.native/logs`,
  `.native/uploads`, 호스트 모델 디렉터리

`docker compose down`과 `./down.sh`는 위 데이터를 보존한다. `docker compose
down -v`는 DB와 cache volume을 제거하므로 데이터 삭제 의도가 없으면 실행하지
않는다.

백업과 복원:

```bash
./backup.sh
./restore.sh --verify-only backups/mininblm-backup-<timestamp>.tar.gz
./restore.sh --yes backups/mininblm-backup-<timestamp>.tar.gz
```

Docker 실행이 기본이며, native 실행은 `RUNTIME_MODE=native`를 지정한다.
`--yes` 복원은 현재 데이터를 교체한다. checksum 검증과 실제 복원 smoke를
Docker 경로에서 확인했다.

## 9. 주요 파일

| 경로 | 역할 |
|---|---|
| `task.md` | 전체 요구사항, 설계 초안, 현재 구현 상태 |
| `README.md` | 사용자용 실행 및 개요 |
| `docs/operations.md` | 운영, 검증, 장애 대응 |
| `docs/frontend-design.md` | FE 요구사항과 구조 설계 |
| `docs/retrieval-presets.md` | preset 및 검색 알고리즘 정책 |
| `docs/retrieval-evaluation.md` | retrieval 평가 fixture, 지표와 benchmark 결과 |
| `docs/reasoning-evaluation.md` | 실제 수업자료 복합 추론, 수동 rubric과 text-only 한계 평가 |
| `docker-compose.yml` | 운영 4개 서비스 |
| `Dockerfile.all-in-one` | PostgreSQL·BGE-M3·vLLM·API 통합 배포 이미지 |
| `docker-compose.all-in-one.yml` | GPU·volume·환경을 포함한 원샷 통합 실행 |
| `docker-compose.test.yml` | 빠른 테스트용 임시 DB |
| `docker-compose.e2e.yml` | 실제 모델 E2E용 API/DB |
| `docker-compose.benchmark.yml` | retrieval benchmark용 격리 DB/runner |
| `run.sh`, `down.sh` | 전체 서비스 시작/종료 |
| `run-native.sh` | Docker 없는 서버의 설치·진단·4개 process 시작/종료 |
| `scripts/test.sh` | 단위/API 통합 테스트 진입점 |
| `scripts/e2e.sh` | 실제 모델 E2E 진입점 |
| `backup.sh`, `restore.sh` | Docker/native PostgreSQL·uploads 백업 bundle 생성 및 복원 |
| `scripts/benchmark-retrieval.sh` | preset/알고리즘 품질·지연 benchmark 진입점 |
| `scripts/benchmark-reasoning.sh` | 문서군별 실제 LLM 복합 추론 benchmark 진입점 |
| `evaluation/` | 버전 관리되는 질문/source fixture와 혼동 문서 |
| `app/evaluation/` | fixture 검증, metric 계산과 benchmark runner |
| `app/main.py` | FastAPI 조립 및 lifespan |
| `app/observability.py` | request ID, JSON 로그와 Prometheus metric |
| `app/api/` | HTTP API router |
| `app/services/` | 문서 처리, 검색, 답변, 복구 orchestration |
| `app/repositories/` | SQLAlchemy DB 접근 |
| `app/storage/local_storage.py` | 로컬 PDF 저장소 |
| `app/services/upload_validation.py` | PDF 업로드 검증 |
| `app/static/` | Vanilla JS Web UI |
| `embedding_service/` | BGE-M3 HTTP 서비스 |
| `alembic/versions/` | DB migration |
| `tests/unit/` | DB 불필요 단위 테스트 |
| `tests/integration/` | 격리 DB API 통합 테스트 |
| `tests/e2e/` | 실제 embedding/LLM E2E |

## 10. 알려진 제한사항

- 이전 대화 생성 문맥은 최근 8개 메시지, 최대 8,000자로 제한된다.
- retrieval query rewriting은 장기 대화 전체가 아닌 직전 질문·답변 한 쌍만
  사용하며, 재작성 LLM 호출이 실패하면 원문 질문으로 검색한다.
- 모든 질문은 검색 계획 LLM 호출이 1회 추가되고, 검색 결과가 있으면 근거
  충족도 호출도 1회 추가된다. 부족 판정이 지속되면 표적 chunk 검색과 page
  계층 fallback을 합쳐 최대 2회, 충족도 판정은 최대 3회 수행한다.
- 답변에 문장별 유효 인용이 빠졌을 때만 인용 보정 LLM 호출이 최대 1회
  추가된다. 완전한 인용 답변과 자료 부재 답변은 보정 호출을 생략한다.
- 문서 처리와 재인덱싱이 API process의 background task를 사용한다.
- 별도 worker/영속 queue가 없어 API process 수명과 자원을 공유한다.
- scanned PDF 전용 OCR은 없지만 선택된 visual page는 Vision caption으로 검색 가능하다.
- Vision caption은 API background task에서 페이지당 1장씩 순차 생성하므로 큰 PDF의
  처리 시간이 늘고 API process가 종료되면 기존 복구 흐름에 의존한다.
- 현재 W4A16 Vision 품질은 Manual 19페이지 단일 사례만 실측했으며 전체 문서군
  반복 benchmark와 vision connector BF16 재양자화 비교가 필요하다.
- 새 layout/시각 위험 메타데이터는 재인덱싱 이후 기존 업로드 문서에 적용된다.
- Prometheus 수집 서버, 대시보드와 경보 규칙은 아직 배포하지 않는다.
- 이메일 기반 셀프서비스 비밀번호 재설정, 계정 잠금과 rate limit은 없다.
- 기본 HTTP/LAN 설정은 `AUTH_COOKIE_SECURE=false`다.
- 업로드 파일 자체는 50MB로 제한하지만 reverse proxy 수준의 전체 request body
  제한은 별도로 구성하지 않았다.

## 11. 남은 작업 권장 순서

### 1순위: 운영 전 필수 보강

- HTTPS reverse proxy와 `AUTH_COOKIE_SECURE=true` 운영 구성
- 회원가입/로그인 rate limit, 계정 잠금과 이메일 기반 셀프서비스 비밀번호 재설정
- PostgreSQL 및 업로드 원본 bundle의 격리 환경 복원 리허설
- Prometheus 수집·대시보드·경보 규칙 구성
- 검증된 vLLM base digest/version 고정과 custom image tag 정합성 확보
- reverse proxy request body 제한을 애플리케이션의 50MB 제한과 일치시킴
- 환경변수 선택을 넘어선 관리자 런타임 모델 전환 API/UI

### 2순위: 처리 안정성과 RAG 품질 확장

- Redis + RQ/Celery worker로 문서 처리와 재인덱싱 분리
- MinIO/S3 object storage 전환
- 다양한 업무·교육 문서로 평가 fixture 확대
- 복합 추론 실패 사례 3회 반복, visual-only 답변 제한과 coverage 형식 안정화
- 도메인별 용어·약어 정규화 및 reranker 비교
- scanned PDF OCR과 text+vision 전체 문서군 반복 benchmark
- 문서 버전 관리, 이메일 인증, 학습 피드백

## 12. Git 및 작업공간 주의사항

Git baseline은 `ceb4d37 V0.3.0`이다. 이후 통합 readiness, 작업공간 전체 검색,
source 문서명, 문서 선택 제거, 대화 세션, 스트리밍·관측성, 계정 생명주기와
복합 RAG 검색이 순서대로 반영되었다. 2026-08-07 현재 로컬 `main`의 최신
통합 commit은 `ece7d7e`이며 `origin/main`보다 4개 commit 앞서 있어 push가
필요하다. 최초
commit에 실수로 포함된
`id_container` RSA private key는 commit amend, reflog 만료 및 unreachable object
정리를 통해 작업공간과 전체 로컬 이력에서 제거했다. Remote `origin`은 GitHub
저장소로 설정되어 있다.

현재 `.gitignore`는 다음 대용량/민감 경로를 제외한다.

- `.env`
- `data/`
- `id_container` 및 private-key 파일 패턴
- `google/` (현재 약 7.2GB)
- `google-gemma-4-12B-it-W4A16-w4a16.tar` (현재 약 7.2GB)
- `*.tar`
- `*:Zone.Identifier`

2026-08-05에 작업공간의 50MB 초과 파일을 전수 확인했으며, 모델 weight와 tar는
각각 `google/`, `*.safetensors`, `*.tar` 규칙에, CUDA 라이브러리는 `.venv`
규칙에 의해 모두 제외되는 것을 `git check-ignore`로 검증했다. 기존 사용자
데이터와 모델 파일은 코드 저장소에 포함하지 않는다.

새 작업을 commit하기 전 `git status --short`와 실제 staging 목록을 확인한다.
현재 `sample/`에는 수동 테스트용 PDF가 로컬에만 있으며 `/sample/` 규칙으로
Git과 Docker build context에서 제외된다. `7cb7cec`에도 포함되지 않았고,
평가 runner는 이 디렉터리를 컨테이너에 read-only bind mount한다.

또한 작업공간에 사용자가 만든 변경이 있을 수 있으므로 확인 없이 파일을
되돌리거나 `git reset --hard`, `git checkout --`, `down -v` 같은 파괴적 명령을
사용하지 않는다.
