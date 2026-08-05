# Retrieval Quality Evaluation

## 목적과 범위

이 평가는 LLM 답변 생성과 분리해 retrieval 단계의 순위 품질과 지연을 비교한다.
동일 corpus를 5개 청킹 preset으로 실제 재청킹·BGE-M3 임베딩하고, 각 preset에서
Dense, Keyword, Substring, Hybrid 알고리즘을 실행한다. 운영 DB와 업로드 파일은
사용하지 않는다.

평가 corpus는 다음 두 PDF의 12페이지로 구성한다.

- `sample_fall_prevention.pdf`: 정답이 있는 4페이지 문서
- `evaluation/retrieval_distractor_nursing_topics.pdf`: 8페이지 혼동 문서

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
| Keyword | 0.125 | 0.125 | 1.91~2.25 ms |
| Substring | 1.000 | 1.000 | 6.32~11.02 ms |
| Hybrid | 1.000 | 0.875~0.938 | 48.42~61.91 ms |

현재 fixture에서는 Substring이 가장 높은 순위 품질과 낮은 지연을 보였다.
Keyword는 `plainto_tsquery`가 자연어 질문의 토큰을 AND 조건으로 결합해 대부분
빈 결과를 반환했다. 이 결과는 Keyword query 구성 개선이 필요하다는 근거다.

이 corpus는 합성된 12페이지 자료이므로 운영 기본 알고리즘을 결정하기에는 작다.
실제 간호학 강의 PDF, 약어·영문 혼합 질문, 복수 정답 페이지와 자료 밖 질문을
fixture에 추가한 뒤 결과를 다시 비교해야 한다.
