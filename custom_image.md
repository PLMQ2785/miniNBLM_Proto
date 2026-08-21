# miniNBLM RunPod Custom Image 배포

Gemma 4 12B·31B 원샷 이미지를 Docker Hub에 게시하고 NVIDIA H200 기반 RunPod Pod에서 실행하기 위한 설정입니다.

## 1. 이미지와 외부 모델

두 `linux/amd64` image는 다음 런타임을 포함하지만 Gemma weight는 포함하지 않습니다.

- PostgreSQL 17 및 pgvector
- BGE-M3 embedding service
- vLLM 0.25.0 및 Gemma 4 호환 patch
- FastAPI와 Web UI
- 모델 archive 다운로드·checksum 검증·원자적 설치 도구

모델 디렉터리는 `tar` 또는 `tar.gz` archive로 별도 storage에 게시합니다. 첫 기동 시
Entrypoint가 archive를 `/data/model-cache`로 이어받고 SHA-256을 확인한 후
`/data/models/gemma4`에 설치합니다. 설치된 모델은 `/data` volume에서 재사용됩니다.

```bash
tar -cf gemma4-12b-w4a16.tar -C ./google gemma-4-12B-it-W4A16
sha256sum gemma4-12b-w4a16.tar
```

archive는 `config.json`과 Safetensors가 root 또는 단일 최상위 디렉터리 안에
있어야 합니다. 현재 12B archive의 검증값은 다음과 같습니다.

```text
Archive: gemma-4-12B-it-W4A16.tar
SHA-256: c7656a53d8652e9d01ae428abcd6780642270b070a73f1923efeba99ac435694
```

31B archive도 생성하고 실제 파일의 SHA-256을 확인했습니다.

```text
Archive: gemma-4-31B-it-W4A16.tar
SHA-256: 1a28093ac67542780473b4c74f659fb3988d7c69e1fbf974772b2ab94c0f6ebf
```

Safetensors는 이미 압축 효율이 낮으므로 `tar.gz`가 전송 크기를 크게 줄이지 못할 수
있습니다. 개선 효과는 모델을 Docker Hub layer에서 분리해
작은 runtime image를 빠르게 pull하고, 더 빠른 object storage/CDN에서 weight를
받는 데서 나옵니다.

공통 image 계약:

```text
Architecture: linux/amd64
Entrypoint: /usr/local/bin/all-in-one-entrypoint
Model cache: /data/models/gemma4
HTTP port: 8080/tcp
Persistent application data: /data
```

## 2. Docker Hub 게시

현재 release namespace는 `cpsu/mininblm`입니다. 12B·31B `0.1.3` compatibility
tag와 `0.1.4` release tag는 모두 `VLLM_MAX_MODEL_LEN=16384`로 build합니다.

```bash
docker login
docker push cpsu/mininblm:0.1.3-gemma4-12b-w4a16
docker push cpsu/mininblm:0.1.3-gemma4-31b-w4a16
docker push cpsu/mininblm:0.1.4
docker push cpsu/mininblm:0.1.4-gemma4-12b-w4a16
docker push cpsu/mininblm:0.1.4-gemma4-31b-w4a16
```

Vast.ai Template에 `VLLM_MAX_MODEL_LEN`이 있으면 image 기본값보다 우선합니다.
12B·31B Template 모두 값을 `16384`로 맞춰야 합니다.

Private repository라면 RunPod Template에 Docker Hub registry credentials를
등록합니다. 모델 archive를 별도 storage에 게시하기 전에 해당 모델의 재배포 조건과
storage 접근 범위를 확인해야 합니다.

## 3. RunPod Custom Template 공통 설정

12B와 31B용 Custom Template을 각각 생성합니다.

| RunPod 항목 | 설정 |
|---|---|
| Container Image | variant별 Docker Hub image |
| Container Start Command | 비워 둠; image Entrypoint 유지 |
| GPU | NVIDIA H200 1장 |
| Expose HTTP Ports | `8080` |
| Expose TCP Ports | 필요하지 않으면 비워 둠 |
| Persistent Volume Mount Path | `/data` |

권장 disk 시작값:

| Variant | Container Disk | `/data` Volume/Network Volume |
|---|---:|---:|
| 12B | 25GB 이상 | 30GB 이상 |
| 31B | 25GB 이상 | 50GB 이상 |

Container Disk는 모델 없는 runtime image와 writable layer를 수용합니다. `/data`
volume은 설치된 모델과 다운로드 중인 Hugging Face snapshot 또는 archive를
수용합니다. 완료된 Hugging Face snapshot은 모델 경로로 이동하며, archive 방식은
기본 `MODEL_KEEP_ARCHIVE=false`일 때 설치 후 archive를 삭제합니다.

```text
/data/models/gemma4  설치된 Gemma 모델
/data/model-cache    다운로드 중인 snapshot/archive와 lock
/data/postgres       PostgreSQL data
/data/uploads        업로드 PDF
/data/huggingface    BGE-M3 cache
/data/backups        백업 bundle
/data/logs           서비스 로그
```

Pod 삭제 후에도 모델, 업로드 PDF와 설정을 유지하려면 Pod 수명에 종속되는 Volume
Disk보다 Network Volume을 사용합니다. mount path는 반드시 `/data`입니다.

Network Volume의 PostgreSQL 영속 가능 여부는 mount 소유권 정책에 달려 있습니다.
`chown`이 제한돼도 data 경로 UID가 `nobody`처럼 container 사용자와 대응하면 해당
사용자로 실행합니다. data 경로가 고정된 root 소유이면 PostgreSQL은 root 실행을
거부하므로 Network Volume에 DB cluster를 둘 수 없습니다. 이 경우 임시 smoke는
local container disk 경로를 사용하고, 영속 운영은 외부 PostgreSQL을 사용합니다.

RunPod HTTP proxy URL:

```text
https://<POD_ID>-8080.proxy.runpod.net
```

Readiness URL:

```text
https://<POD_ID>-8080.proxy.runpod.net/health/ready
```

정상 응답은 HTTP 200이며 `database`, `embedding`, `llm` component가 모두 `ok`여야 합니다.

## 4. 공통 환경변수

```dotenv
NATIVE_DB_NAME=rag_db
NATIVE_DB_USER=rag_user
NATIVE_DB_PASSWORD=<충분히-긴-무작위-DB-비밀번호>

VLLM_MODEL_PATH=/data/models/gemma4
MODEL_HF_REPO_ID=<Hugging-Face-owner/repository>
MODEL_HF_REVISION=<40자리-commit-SHA>
HF_HOME=/data/huggingface

MAX_UPLOAD_BYTES=52428800
MAX_REQUEST_BODY_BYTES=53477376
VISION_CAPTION_MODE=disabled
READINESS_TIMEOUT_SECONDS=3
AUTH_SESSION_TTL_HOURS=168
AUTH_COOKIE_SECURE=true
LOG_LEVEL=INFO
STARTUP_TIMEOUT=1800
```

Hugging Face 방식은 공개 repository와 변경되지 않는 40자리 commit SHA를 사용합니다.
Entrypoint가 `hf download`로 중단된 snapshot을 이어받고 `config.json`과
Safetensors를 확인한 뒤에만 모델 경로로 이동합니다.

archive 방식을 사용하려면 `MODEL_HF_*` 대신 다음 세 변수를 설정합니다. 두 방식을
동시에 설정할 수 없습니다.

```dotenv
MODEL_ARCHIVE_URL=<모델-archive-직접-다운로드-URL>
MODEL_ARCHIVE_SHA256=<64자리-SHA-256>
MODEL_KEEP_ARCHIVE=false
```

archive URL은 공유 HTML 페이지가 아니라 `curl -L`로 파일 본문을 받을 수 있어야
합니다. S3/R2 presigned URL은 Pod 재생성 전에 만료 여부를 확인하고, checksum은
실제 업로드한 archive에서 계산합니다.

주의사항:

- `NATIVE_DB_PASSWORD`가 기본값 `rag_password`이면 Entrypoint가 실행을 거부합니다.
- `AUTH_COOKIE_SECURE=true`는 RunPod HTTPS proxy 접속 기준입니다.
- 모델이 이미 완전하게 설치되어 있고 source marker가 일치하면 원격 저장소에 접근하지 않습니다.
- Hugging Face와 archive 다운로드 모두 `.part` 경로를 재사용해 다음 시작에서 이어받습니다.
- checksum 불일치 archive는 삭제하며 모델 경로에 설치하지 않습니다.
- BGE-M3 최초 적재에도 public Hugging Face outbound network가 필요합니다.

Bootstrap 관리자가 필요할 때만 다음 두 변수를 함께 설정합니다.

```dotenv
BOOTSTRAP_ADMIN_USERNAME=<initial-admin>
BOOTSTRAP_ADMIN_PASSWORD=<안전한-임시-비밀번호>
```

최초 로그인 후 비밀번호를 변경했다면 다음 재시작 전에 두 `BOOTSTRAP_ADMIN_*`
변수를 Template에서 제거합니다.

### 4.1 실행 후 Grok endpoint 추가

배포 image와 기본 endpoint JSON에는 실제 API key나 Grok endpoint를 넣지 않습니다.
기본 local `gemma4` endpoint는 `authentication: "none"`으로 시작합니다. 최초
관리자 로그인 후 **관리** 화면에서 Grok endpoint를 추가하고 인증 방식을 `managed`로
선택한 뒤 API key를 입력합니다. 12B와 31B 모두 local endpoint 식별자와 vLLM served
model name은 `gemma4`이며 표시 이름으로 variant를 구분합니다.

관리자가 입력한 API key는 자동 생성된
`/data/secrets/llm/master.key`로 암호화되며 persistent endpoint JSON에는
`api_key_ciphertext`만 저장됩니다. 평문 key와 암호문은 관리 API 응답에 포함되지
않습니다. Endpoint JSON과 master key를 함께 백업하고 master key 권한을 0600으로
유지합니다. Master key를 잃으면 기존 암호문을 복구할 수 없습니다.

Persistent 파일을 직접 점검해야 한다면 JSON 구문만 검증합니다.

```bash
python3 -m json.tool /data/config/llm-endpoints.json >/dev/null
```

## 5. 12B Template

### Image

```text
cpsu/mininblm:0.1.4
```

또는 retag한 image:

```text
<dockerhub-user>/mininblm:0.1.4-gemma4-12b-w4a16
```

### RunPod Raw 환경변수 전체 목록

12B Template의 **Environment Variables → Raw**에 아래 목록을 한 번에 입력합니다.
`<...>` 값은 실제 값으로 교체하고 각 `KEY=VALUE`를 줄바꿈 없이 한 줄에 입력합니다.

```dotenv
NATIVE_DB_NAME=rag_db
NATIVE_DB_USER=rag_user
NATIVE_DB_PASSWORD=<새로-생성한-충분히-긴-무작위-DB-비밀번호>
NATIVE_DB_DATA_DIR=/var/lib/mininblm/postgres
NATIVE_LOG_DIR=/var/log/mininblm

VLLM_MODEL_PATH=/data/models/gemma4
MODEL_HF_REPO_ID=PLMQ2785/Gemma-4-12B-it-W4A16
MODEL_HF_REVISION=5001828f23191ed64c94e9e57ef58fc3b45fa492
HF_HOME=/data/huggingface

EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=cuda

VLLM_MODEL_NAME=gemma4
VLLM_MAX_MODEL_LEN=16384
VLLM_GPU_MEMORY_UTILIZATION=0.65
VLLM_MAX_NUM_SEQS=4
VLLM_CPU_OFFLOAD_GB=0
VLLM_TENSOR_PARALLEL_SIZE=1

LLM_ENDPOINTS_FILE=/data/config/llm-endpoints.json

MAX_UPLOAD_BYTES=52428800
MAX_REQUEST_BODY_BYTES=53477376
VISION_CAPTION_MODE=disabled
VISION_CAPTION_DPI=144
VISION_CAPTION_VERSION=gemma4-page-caption-v1
READINESS_TIMEOUT_SECONDS=3
AUTH_SESSION_TTL_HOURS=168
AUTH_COOKIE_SECURE=true
LOG_LEVEL=INFO
STARTUP_TIMEOUT=1800

BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=<새로-생성한-안전한-임시-관리자-비밀번호>
```

위 `NATIVE_DB_DATA_DIR`은 root 소유 Network Volume을 피하는 smoke 설정입니다.
RunPod container disk는 Pod stop/restart 시 초기화되므로 계정·문서 metadata·대화가
영속되지 않습니다. 영속 운영에서는 `NATIVE_MANAGE_DB=false`와 외부 PostgreSQL
`DATABASE_URL`을 사용합니다. 모델, 업로드 PDF와 endpoint JSON은 계속 `/data`에
저장됩니다.

12B 배포 image의 기본 endpoint JSON에는 인증 없는 local `gemma4`만 포함합니다.
Grok은 image에 포함하지 않으며 첫 실행 후 위 4.1 절의 절차로 추가합니다.
Bootstrap 두 변수는 일회성 테스트에서 유지해도 되며, 장기 운영에서는 최초 로그인과 비밀번호 변경 후
함께 제거합니다.

첫 실행에서 이미지의 12B 기본 등록정보를 `/data/config/llm-endpoints.json`에
생성합니다.

`VLLM_MAX_NUM_SEQS=4`는 vLLM scheduler가 동시에 GPU에서 처리할 활성 sequence 상한입니다. 전체 가입자나 접속자 수 제한이 아닙니다. H200 실제 부하에서 대기 요청, TTFT, 생성 속도, KV cache와 preemption을 확인한 뒤 `8` 또는 `16`과 비교할 수 있습니다.

## 6. 31B H200 Template

### Image

```text
cpsu/mininblm:0.1.4-gemma4-31b-w4a16
```

또는 retag한 image:

```text
<dockerhub-user>/mininblm:0.1.4-gemma4-31b-w4a16
```

### RunPod Raw 환경변수 전체 목록

31B Template의 **Environment Variables → Raw**에 아래 목록을 한 번에 입력합니다.
secret placeholder는 실제 값으로 교체합니다. 아래 URL은 브라우저 공유 화면이 아닌
검증된 Google Drive 직접 다운로드 URL입니다.

```dotenv
NATIVE_DB_NAME=rag_db
NATIVE_DB_USER=rag_user
NATIVE_DB_PASSWORD=<충분히-긴-무작위-DB-비밀번호>

VLLM_MODEL_PATH=/data/models/gemma4
MODEL_ARCHIVE_URL=https://drive.usercontent.google.com/download?id=1sRf_b2PflYVmzF-deNmjoT8NL1Y_W373&export=download&confirm=t
MODEL_ARCHIVE_SHA256=1a28093ac67542780473b4c74f659fb3988d7c69e1fbf974772b2ab94c0f6ebf
MODEL_KEEP_ARCHIVE=false
HF_HOME=/data/huggingface

EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=cuda

VLLM_MODEL_NAME=gemma4
VLLM_MAX_MODEL_LEN=16384
VLLM_GPU_MEMORY_UTILIZATION=0.70
VLLM_MAX_NUM_SEQS=8
VLLM_CPU_OFFLOAD_GB=0
VLLM_TENSOR_PARALLEL_SIZE=1

LLM_ENDPOINTS_FILE=/data/config/llm-endpoints.json

MAX_UPLOAD_BYTES=52428800
MAX_REQUEST_BODY_BYTES=53477376
VISION_CAPTION_MODE=disabled
VISION_CAPTION_DPI=144
VISION_CAPTION_VERSION=gemma4-31b-page-caption-v1
READINESS_TIMEOUT_SECONDS=3
AUTH_SESSION_TTL_HOURS=168
AUTH_COOKIE_SECURE=true
LOG_LEVEL=INFO
STARTUP_TIMEOUT=1800

BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=<안전한-임시-관리자-비밀번호>
```

RunPod Network Volume의 `/data/postgres`가 root 소유이고 `chown`을 거부하면 12B와
동일하게 다음 두 변수를 추가합니다. Vast의 persistent volume이 `chown`을 허용하면
추가하지 않고 기본 `/data/postgres`를 사용해야 DB가 영속됩니다.

```dotenv
NATIVE_DB_DATA_DIR=/var/lib/mininblm/postgres
NATIVE_LOG_DIR=/var/log/mininblm
```

31B 배포 image의 기본 endpoint JSON에도 인증 없는 local `gemma4`만 포함하며
표시 이름은 `Gemma 4 31B W4A16`입니다.
Grok은 image에 포함하지 않으며 첫 실행 후 위 4.1 절의 절차로 추가합니다.

첫 실행에서 이미지의 31B 기본 등록정보를 `/data/config/llm-endpoints.json`에
생성합니다.

이 profile의 전제:

- H200 한 장에서 miniNBLM vLLM 인스턴스 하나와 BGE-M3를 실행합니다.
- vLLM은 전체 GPU VRAM의 70%를 목표로 사용합니다.
- 최대 8개 활성 sequence가 동일한 model weight와 KV cache pool을 공유합니다.
- 요청 8개가 각각 VRAM 70%를 예약하는 구조가 아닙니다.
- H200 한 장이므로 tensor parallel은 `1`입니다.
- CPU offload는 사용하지 않습니다.

같은 GPU에 별도 vLLM 프로세스를 추가하면 각 프로세스의 `VLLM_GPU_MEMORY_UTILIZATION`이 중첩됩니다. `0.70`은 miniNBLM vLLM 인스턴스 하나만 실행한다는 전제입니다.

## 7. 최초 실행과 확인

기동 순서:

1. RunPod가 모델 없는 custom image를 pull합니다.
2. Entrypoint가 DB 비밀번호와 API endpoint JSON을 검증합니다.
3. 모델 archive를 이어받고 SHA-256을 검증합니다.
4. 임시 경로에서 `config.json`과 Safetensors를 확인하고 `/data/models/gemma4`에 설치합니다.
5. PostgreSQL, BGE-M3와 vLLM을 시작합니다.
6. Alembic migration 후 API와 Web UI를 시작합니다.

최초 기동은 모델 다운로드·압축 해제, BGE-M3 cache 다운로드와 vLLM model 적재
때문에 오래 걸립니다. 이후 기동에는 `/data/models/gemma4`를 재사용합니다.

Readiness 확인:

```bash
curl -fsS https://<POD_ID>-8080.proxy.runpod.net/health/ready
```

기대 조건:

```text
HTTP 200
database.status = ok
embedding.status = ok
llm.status = ok
```

기능 smoke:

1. Web UI 접속
2. 회원가입 또는 bootstrap 관리자 로그인
3. PDF 업로드
4. 문서 상태가 `indexed`가 될 때까지 대기
5. 문서 내용 질문
6. 답변과 실제 PDF page source 확인

문제 발생 시 우선 확인:

- 다운로드 403/HTML 응답: 공유 페이지가 아닌 직접 다운로드 URL인지 확인
- checksum 오류: 업로드를 마친 최종 archive에서 다시 `sha256sum` 실행
- 불완전 모델 경로: `/data/models/gemma4`를 비운 뒤 재시작
- 디스크 부족: archive와 압축 해제본이 동시에 들어갈 `/data` 여유 공간 확인
- DB 비밀번호 거부: `NATIVE_DB_PASSWORD`가 기본값인지 확인
- 8080 접속 실패: RunPod `Expose HTTP Ports`와 container log 확인
- BGE-M3 최초 적재 실패: outbound network와 `/data/huggingface` 쓰기 권한 확인
- CUDA OOM: 같은 GPU의 다른 프로세스와 `VLLM_GPU_MEMORY_UTILIZATION` 확인
- KV cache 부족 또는 preemption: `VLLM_MAX_NUM_SEQS` 또는 `VLLM_MAX_MODEL_LEN` 감소

## 8. 현재 검증 범위

완료:

- 12B model archive SHA-256 계산
- downloader의 checksum 검증, 원자적 설치, 재시작 cache 재사용 자동화 테스트
- model build context와 model `COPY` 제거
- image label `io.mininblm.model.bundled=false`, delivery `remote-archive` 적용

배포 서버에서 추가 확인:

- 실제 storage의 12B·31B 대용량 archive 다운로드 및 이어받기
- 12B/31B readiness와 실제 completion
- 동시 요청의 TTFT, 처리량과 preemption

RunPod 공식 참고 문서:

- [Pod templates](https://docs.runpod.io/pods/templates/overview)
- [Custom Pod template](https://docs.runpod.io/pods/templates/create-custom-template)
- [Storage options](https://docs.runpod.io/pods/storage/types)
