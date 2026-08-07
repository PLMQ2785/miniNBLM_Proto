# Retrieval Quality Evaluation

## 목적과 범위

이 평가는 LLM 답변 생성과 분리해 retrieval 단계의 순위 품질과 지연을 비교한다.
동일 corpus를 5개 청킹 preset으로 실제 재청킹·BGE-M3 임베딩하고, 각 preset에서
Dense, Keyword, Substring, Hybrid 알고리즘을 실행한다. 운영 DB와 업로드 파일은
사용하지 않는다.

평가 corpus는 다음 두 PDF의 12페이지로 구성한다.

- `sample_fall_prevention.pdf`: 정답이 있는 4페이지 문서
- `evaluation/retrieval_distractor_nursing_topics.pdf`: 8페이지 검색 혼동 문서

버전 관리되는 `evaluation/retrieval_fall_prevention.json`에 8개 질문과 정답
`문서명 + 페이지`를 기록한다. 혼동 문서는
`scripts/generate_retrieval_distractor_pdf.py`로 재생성할 수 있다.

## 지표

| 지표 | 의미 |
|---|---|
| `Recall@K` | 정답 source 중 상위 K개 chunk가 포함한 source 비율 |
| `Hit rate@K` | 질문별 상위 K개에 정답 source가 하나라도 있는 비율 |
| `MRR@K` | 첫 정답 chunk 순위의 역수 평균 |
| `p50/p95 latency` | query embedding을 포함한 retrieval 호출 지연 |
| `Index ms` | 해당 preset으로 전체 평가 문서를 재청킹·임베딩한 시간 |

평가 cutoff 기본값은 `K=5`다. 실제 retrieval 요청 수는 각 preset의 `top_k`를
그대로 사용하고, 품질 계산만 상위 5개로 제한한다. 동일 페이지의 여러 chunk는
Recall 계산에서 중복 source로 세지 않는다.

## 실행

운영 embedding 서비스가 `127.0.0.1:8070`에서 준비된 상태에서 실행한다. LLM은
필요하지 않다.

```bash
./scripts/benchmark-retrieval.sh
```

스크립트는 다음 작업을 자동화한다.

1. `docker-compose.benchmark.yml`의 tmpfs PostgreSQL을 시작한다.
2. API dependency만 포함한 benchmark runner 이미지를 빌드한다.
3. 격리 DB에 Alembic migration을 적용한다.
4. 5 preset x 4 알고리즘 matrix를 평가한다.
5. 임시 DB와 runner를 삭제한다.

JSON 상세 결과와 Markdown 표는 `benchmark_results/retrieval/`에 생성되며 Git에서
제외된다. JSON에는 fixture와 각 PDF의 SHA-256, 질문별 검색 순위와 지연 sample이
포함된다.

빠른 smoke 또는 일부 조합만 실행할 수 있다.

```bash
./scripts/benchmark-retrieval.sh --warmup 0 --iterations 1
./scripts/benchmark-retrieval.sh \
  --preset balanced \
  --algorithm dense \
  --algorithm hybrid \
  --minimum-recall 0.8
```

`--minimum-recall`보다 낮은 선택 조합이 있으면 결과 파일을 저장한 뒤 exit code
2를 반환한다. `--evaluation-k`, `--warmup`, `--iterations`로 측정 조건을 바꿀 수
있다.

## 2026-08-05 기준 결과

조건은 warmup 1회, 질문별 측정 3회, `K=5`다.

| 알고리즘 | Recall@5 범위 | MRR@5 범위 | p50 지연 범위 |
|---|---:|---:|---:|
| Dense | 0.875~1.000 | 0.713~0.833 | 35.84~41.31 ms |
| Keyword | 1.000 | 0.854~0.938 | 5.99~11.42 ms |
| Substring | 1.000 | 1.000 | 6.32~11.02 ms |
| Hybrid | 1.000 | 0.875~0.938 | 48.42~61.91 ms |

Keyword는 최초 측정에서 `plainto_tsquery`의 전체 토큰 AND 조건 때문에
Recall@5가 `0.125`였다. 2026-08-06에 토큰별 `plainto_tsquery`를 OR로 결합하도록
개선한 뒤 5개 preset 모두 Recall@5 `1.000`을 기록했다. 위 Keyword 지연과 MRR은
개선 후 동일한 warmup 1회, 질문별 3회 조건으로 다시 측정한 값이다.

현재 fixture에서는 Substring과 개선된 Keyword가 모두 Recall@5 `1.000`이다.
Substring은 MRR `1.000`으로 순위 품질이 더 높고, Keyword는 형태가 정확히
일치하는 핵심어가 있는 질의에서 해석하기 쉬운 FTS 점수를 제공한다.

이 corpus는 합성된 12페이지 자료이므로 운영 기본 알고리즘을 결정하기에는 작다.
실제 사용 분야의 PDF, 약어·영문 혼합 질문, 복수 정답 페이지와 자료 밖 질문을
fixture에 추가한 뒤 결과를 다시 비교해야 한다.

## 복합 질의 회귀 평가

`evaluation/retrieval_multihop_oss.json`은 Git 작업 흐름과 오픈소스 라이선스의
복합 질의를 재현한다. 운영 업로드 경로나 사용자 데이터에 의존하지 않도록 다음
소형 PDF를 버전 관리한다.

- `evaluation/retrieval_multihop_git.pdf`: ignore/stash, reset/revert, DVCS 협업
- `evaluation/retrieval_multihop_licenses.pdf`: AGPL, MPL 호환성, 하이브리드 고지

schema version 2의 각 case에는 다음 항목이 추가된다.

- `retrieval_queries`: 질의 분해 결과를 재현하는 최대 4개 검색 질의
- `evidence_facets`: 답변에 필요한 근거 단위와 정답 source
- `required_answer_claims`: 후속 답변 품질 평가에서 확인할 필수 주장

결정적인 `retrieval_queries`를 fixture에 기록하므로 LLM의 질의 계획 출력 변동과
분리해 다중 질의 검색, RRF, 인접 청크 확장을 회귀 검증할 수 있다.

```bash
./scripts/benchmark-retrieval.sh \
  --fixture evaluation/retrieval_multihop_oss.json \
  --preset balanced \
  --algorithm hybrid \
  --warmup 0 \
  --iterations 1 \
  --evaluation-k 3 \
  --minimum-recall 1.0
```

Dense와 Hybrid는 각 하위 질의의 1위 후보를 보존한 뒤 초기 검색의 `top_k × 3`
후보를 재정렬한다. 점수는 BGE-M3 의미 유사도 80%와 기존 후보 순위 20%를
결합하며, 의미 유사도는 원 질문 70%와 하위 질의 최대 유사도 30%로 구성한다.
하위 질의별 최상위 의미 후보도 최종 결과에 하나씩 보존한다. Keyword와
Substring은 선택한 알고리즘의 순수 순위를 유지하며, 재정렬 실패 시 기존 순위로
폴백한다.

실제 채팅 경로는 이 검색 결과에 대해 근거 충족도를 검사한다. 부족한 전제와
표적 검색어가 반환되면 표적 chunk 검색과 page FTS·trigram 계층 fallback을
최대 2회 수행한다. 계층 검색은 세부 질의별 page anchor를 보존하고 선택한
페이지와 겹치는 chunk를 BGE-M3로 재정렬한다. 모든 재검색 결과는 기존 Context와
중복 제거해 병합하며 빈 결과가 기존 Context를 지우지 않는다. 최종 충족도 판정은
작은 모델의 과잉 거부 가능성 때문에 답변을 직접 차단하지 않고 검색 제어 및
관측에 사용한다. 이 LLM 판정은 결정적인 retrieval benchmark 점수에는 포함하지
않으며 실제 모델 E2E로 별도 확인한다.

답변 생성 후에는 실질 문장별 Source/Page를 검색 Context와 대조한다. 인용이
누락되거나 번호·페이지가 맞지 않을 때만 보정 LLM을 최대 한 번 호출한다. 이
단계는 retrieval Recall/MRR과 분리된 생성 품질 계층이며, 실제 모델 E2E에서는
필수 주장 존재 여부와 함께 인용된 Source/Page의 유효성도 확인해야 한다.

2026-08-07 기준 `balanced + hybrid`, warmup 0, 질문별 1회 조건에서 장문·간접
표현을 포함한 7개 case의 Recall@3, Hit rate@3, MRR@3은 모두 `1.000`이었다.
p50은 `219.52 ms`, p95는 `265.54 ms`였으며, 소형 corpus의 단일 실행 결과이므로
운영 SLO로 사용하지 않는다.
평가 PDF는 다음 명령으로 다시 생성할 수 있다.

```bash
uv run python scripts/generate_multihop_retrieval_fixture_pdfs.py
```
