# 복합·다층 추론 RAG 평가

## 목적

`sample/`의 실제 수업자료와 장비 매뉴얼을 사용해 단순 키워드 검색보다 어려운
질문을 검증한다. 최종 답변의 성공·실패만 기록하지 않고 다음 단계를 분리한다.

1. PDF에서 필요한 근거가 텍스트로 추출됐는가?
2. 질의 계획이 필요한 하위 문제를 만들었는가?
3. 초기 검색과 최대 2회 재검색이 정답 페이지를 회수했는가?
4. 모델이 여러 페이지의 근거를 올바르게 결합했는가?
5. 답할 수 없는 부분을 추측하지 않고 제한을 밝혔는가?
6. 최종 주장에 실제 Source/Page 인용이 연결됐는가?

초기 기준선에서는 답변을 생성한 LLM을 다시 judge로 사용하지 않는다. runner가
검색·인용·거부 동작을 자동 점검하고, 의미적 정확성과 완전성은 사람이 rubric으로
검토한다.

## 평가 자료

로컬 `sample/`은 다음 세 문서군으로 구성된다.

| Group | 문서 수 | 주된 검증 대상 |
|---|---:|---|
| `Manual` | 1 | 설정 절차, 통신 응답 해석, 화면 캡처 한계 |
| `OpenSWDesign` | 11 | SRUP 산출물 추적, UML 모델 일관성, 다이어그램 한계 |
| `OpenSWUnderstand` | 7 | Git 협업·복구와 라이선스 조건의 다중 근거 결합 |

PDF는 수업·업무 자료일 수 있으므로 Git에 자동 추가하지 않는다. 평가 fixture에는
파일명, 질문, 정답 페이지와 검토 기준만 기록한다.

## 질문 분류

`evaluation/sample_multilayer_reasoning.json`은 10개 초기 사례를 정의한다.

- `answerability=full`: 텍스트 Context만으로 완전한 답변 가능
- `answerability=partial`: 일부 결론만 자료가 뒷받침하며 한계 고지가 필요
- `answerability=none`: 현재 text-only Context로는 답할 수 없음
- `evidence_modality=text`: 필요한 근거가 텍스트 레이어에 존재
- `evidence_modality=mixed`: 텍스트와 화면·표 배치를 함께 사용
- `evidence_modality=visual_only`: 핵심 근거가 이미지나 도형에만 존재

기대 동작은 다음 세 가지다.

| 기대 동작 | 통과 조건 |
|---|---|
| `grounded_answer` | 필수 주장을 모두 설명하고 유효한 근거 페이지를 인용 |
| `qualified_answer` | 확인 가능한 부분만 답하고 자료가 없는 결론을 명시적으로 제한 |
| `abstain` | 근거 없는 값·관계·화면 내용을 추측하지 않고 source 없이 거부 |

시각 전용 질문의 육안 정답은 오직 평가자용이다. 모델이 우연히 같은 값을
말하더라도 text Context에 근거가 없다면 정답으로 처리하지 않는다.

## Text-only 감사

먼저 페이지별 텍스트 문자 수, image block과 vector drawing 수를 기록한다.

```bash
uv run python -m app.evaluation.pdf_text_audit sample \
  --output benchmark_results/reasoning/pdf-audit.json
```

감사의 `risk`는 자동 경고이며 정답 판정 자체는 아니다.

- `empty_text`: 추출 텍스트 없음
- `visual_heavy`: 텍스트가 100자 미만이고 이미지·도형 비중이 큼
- `low_text`: 텍스트가 100자 미만
- `mixed`: 텍스트와 이미지·도형이 함께 있음
- `text`: 텍스트 중심

배경 이미지가 있는 슬라이드는 `mixed`로 과대 집계될 수 있다. 따라서
`visual_only` 사례는 원본 페이지를 사람이 확인하고 fixture에 명시한다.

현재 확인된 대표적 한계는 다음과 같다.

- Manual 19페이지 Tera Term 화면의 실제 응답 문자열
- Behavior Modeling II 20페이지 상태 전이·entry/exit 연산과 최종 `x` 계산
- UML 36페이지 sequence diagram의 lifeline과 메시지 순서
- Behavior Modeling I 38페이지 class diagram의 속성·연산·관계

이 정보는 화면에는 보이지만 현재 text-only Context에는 없거나 불완전하다.

## 실행

운영 embedding과 LLM이 각각 `127.0.0.1:8070`, `127.0.0.1:8010`에서 준비된
상태에서 문서군별로 실행한다.

```bash
./scripts/benchmark-reasoning.sh --group Manual
./scripts/benchmark-reasoning.sh --group OpenSWDesign
./scripts/benchmark-reasoning.sh --group OpenSWUnderstand
```

특정 사례만 반복할 수도 있다.

```bash
./scripts/benchmark-reasoning.sh \
  --group OpenSWDesign \
  --case design-state-machine-x-visual-only
```

runner는 전용 tmpfs PostgreSQL을 사용하고 문서군마다 별도 사용자를 생성한다.
운영 DB와 업로드 파일을 수정하지 않는다. 각 문서군을 한 작업공간으로 구성해
다른 과목 자료가 검색 후보를 오염시키는 문제와 핵심 추론 실패를 우선 분리한다.
전체 문서군을 합친 간섭 검증은 문서군별 기준선 이후 수행한다.

결과는 `benchmark_results/reasoning/`의 JSON과 Markdown으로 저장된다. JSON에는
실제 질의 계획, 초기·최종 source/facet recall, page 텍스트 미리보기, 답변,
인용 source와 전체 retrieval trace가 포함된다.

## 수동 판정

각 답변을 다음 기준으로 검토한다.

| 항목 | 0점 | 1점 | 2점 |
|---|---|---|---|
| 주장 정확성 | 핵심 결론 오류 | 일부만 정확 | 모든 필수 주장 정확 |
| 완전성 | 핵심 facet 누락 | 일부 facet 포함 | 모든 facet 결합 |
| 근거성 | 무인용·잘못된 인용 | 일부 주장만 근거 | 모든 핵심 주장에 유효 인용 |
| 한계 보정 | 근거 밖 내용을 단정 | 제한이 모호함 | 확인 불가 범위를 정확히 고지 |

최종 분류는 다음처럼 기록한다.

- `pass`: 기대 동작을 충족하고 핵심 주장·인용에 오류가 없음
- `partial`: 일부 근거·주장은 맞지만 facet 누락, 과도한 거부 또는 제한 고지가 부족
- `fail`: 답할 수 있는 질문을 거부하거나, 근거 없는 답을 생성하거나, 핵심 결론이 틀림

`automatic_gate=review`는 의미 검토가 필요하다는 뜻이고 자동 통과가 아니다.
`automatic_gate=fail`도 원인을 확인해야 하며 곧바로 모델 추론 실패를 뜻하지 않는다.

## 실패 원인 분류

| 관측 | 분류 | 우선 개선 대상 |
|---|---|---|
| 정답 페이지 텍스트가 비어 있거나 핵심 도형 정보가 없음 | `parse_gap` | OCR, layout/table parser, vision caption |
| 텍스트 근거는 있으나 초기·최종 recall이 낮음 | `retrieval_gap` | query planning, chunk/page 검색, reranker |
| 모든 facet이 Context에 있으나 필수 주장 누락 | `reasoning_gap` | 답변 prompt, 모델, context 구성 |
| 답변은 맞지만 Source/Page가 누락·오류 | `citation_gap` | citation validator와 repair |
| 부분 근거만 있는데 전체 결론을 단정 | `calibration_gap` | 근거 충족 판정과 제한 고지 prompt |
| 자료 밖 질문을 source 없이 거부 | `expected_abstention` | 정상 동작 |

이 분류를 먼저 적용한 뒤 개선한다. 예를 들어 visual-only 페이지의 실패를
reranker 문제로 처리하면 검색 순위만 바뀌고 실제 근거는 계속 유실된다.

## 반복 절차

1. 문서군별 기준선을 1회 실행한다.
2. Markdown 답변을 사람이 `pass/partial/fail`로 분류한다.
3. 실패 사례는 위 원인 코드 하나와 보조 원인을 기록한다.
4. 동일 사례를 3회 반복해 생성 변동인지 구조적 실패인지 구분한다.
5. 개선은 한 계층만 변경하고 같은 fixture로 재실행한다.
6. 문서군별 기준선이 안정되면 세 문서군을 합쳐 검색 간섭을 측정한다.

초기 개선 우선순위는 `parse_gap`과 `retrieval_gap`을 분리하는 것이다. OCR이나
Vision을 도입하기 전까지 visual-only 사례의 올바른 결과는 정답 생성이 아니라
근거 부족을 명확히 밝히는 것이다.

## 2026-08-07 1차 기준선

조건은 `balanced + hybrid`, 문서군별 격리 workspace, 실제 BGE-M3와 Gemma 4
12B W4A16이다. 의미 평가는 위 rubric으로 답변을 직접 검토했다.

| Group | Case | Initial/Final recall | 분류 | 주 원인 |
|---|---|---:|---|---|
| Manual | `manual-rs485-response-diagnosis` | 1.00 / 1.00 | pass | 모든 통신 조건과 상태를 결합 |
| Manual | `manual-two-setting-workflow` | 1.00 / 1.00 | pass | 세 설정 facet과 반영 절차를 결합 |
| Manual | `manual-terminal-screenshot-visual-only` | 1.00 / 1.00 | fail | `parse_gap`: 실제 `NLNNN` 대신 본문 예시 `NNNNN` 생성 |
| OpenSWDesign | `design-srup-artifact-traceability` | 0.50 / 0.75 | partial | `reasoning_gap`: state/일관성 누락, 무관한 use-case 관계로 이탈 |
| OpenSWDesign | `design-late-report-qualified-consequence` | 0.00 / 0.00 | fail | `retrieval_gap`: 한글 질의로 영문 감점 페이지 미회수 |
| OpenSWDesign | `design-state-machine-x-visual-only` | 1.00 / 1.00 | fail | `parse_gap`: 육안 정답 4 대신 근거 없는 20 생성 |
| OpenSWUnderstand | `oss-ignore-stash-prerequisite` | 1.00 / 1.00 | partial | 원인은 맞지만 `.gitignore` 해제와 `git add` 선행 작업 누락 |
| OpenSWUnderstand | `oss-pushed-revert-dvcs` | 0.75 / 0.75 | pass | revert/reset/DVCS 근거를 결합, remote facet 직접 회수는 누락 |
| OpenSWUnderstand | `oss-agpl-saas-source-gap` | 1.00 / 1.00 | partial | 안전하게 거부했지만 자료가 지원하는 strong-copyleft 분류도 생략 |
| OpenSWUnderstand | `oss-mpl-gpl-conflict-options` | 1.00 / 1.00 | partial | 구조 분리·대체는 답했지만 MPL-2.0 호환 경로 누락 |

합계는 `pass 3`, `partial 4`, `fail 3`이다. 단일 실행이므로 확률적 안정성을
뜻하지 않으며, 각 실패·경계 사례를 최소 3회 반복한 뒤 회귀 기준으로 확정한다.

추가로 근거 충족도 판정 4건에서 모델 출력 형식이 parser 계약을 지키지 않아
`unchecked` fallback이 작동했다. 기존 Context는 보존됐지만, coverage 출력
정규화와 관측 상태를 보강해야 한다. 인용 보정에서도 유효하지 않은 source 번호가
한 차례 반환됐으며 validator가 이를 거부했다.

`design-late-report` trace에서는 실제 정답이 영문 `Project plan.pdf` 8~10페이지에
있지만 실제 query plan 네 개가 모두 한국어로 생성됐다. 초기 hybrid 후보 24개,
표적 재검색 후보와 page fallback 12개가 모두 한국어 슬라이드에 치우쳐 정답
문서가 후보에 들어오지 않았다. 이 사례는 top-k만 늘리기 전에 원질문과 반대
언어의 보조 질의 생성, dense 후보 최소 할당과 문서 언어 감지를 비교해야 한다.

우선 개선 순서는 다음과 같다.

1. 시각 전용 페이지를 자동 감지해 답변을 제한하여 환각을 차단한다.
2. `design-late-report`에 영문 보조 질의와 dense 후보 최소 할당을 비교한다.
3. Context가 충분한 partial 사례의 필수 facet 체크와 답변 구조를 강화한다.
4. coverage parser의 비정형 출력을 trace에서 구분하고 허용 형식을 정규화한다.
5. 이후 OCR/layout parser 또는 Vision caption을 별도 실험군으로 추가한다.

## 2026-08-07 text-only 1차 개선

다음 항목을 구현했다.

1. PyMuPDF 좌표 block 순서로 본문을 구성하고 반복 머리말·꼬리말과 하단 페이지
   번호를 제거하며, 검출된 표를 행·열 구분이 남는 텍스트로 변환한다.
2. 페이지별 언어, 문자 수, image/drawing/table 수와 시각 근거 위험도를 page 및
   chunk metadata에 저장한다.
3. 페이지가 명시된 화면 전사·다이어그램 계산 질문이 시각 content에 의존하면
   생성 전에 text-only 한계를 반환하고 source를 비운다.
4. 최대 4개 로컬 근거 검색어와 최대 2개 반대 언어 검색어를 분리하고, query plan
   형식 오류는 1회 복구한다. hybrid 검색과 reranker는 방식·질의별 후보를 보존한다.
5. 재검색은 최초 Context를 우선 보존하며, 근거 매트릭스가 일부만 충족됐을 때는
   확인 가능한 부분과 확인 불가능한 결론을 나누어 답한다.
6. embedding query를 서비스 제한인 5개씩 배치하고, 생성 반복 퇴행은 한 번
   재생성하며, 불완전한 Source 표기에 page metadata를 보완한다.

기존 업로드 문서에는 재인덱싱 후 새 metadata가 적용된다. Vision/OCR은 아직
도입하지 않았으므로 시각 전용 질문의 정상 결과는 여전히 명시적 거부다.

최종 전체 실행 보고서는
`benchmark_results/reasoning/reasoning-benchmark-20260807T060016Z.json`이며 결과
파일은 Git에서 제외된다. 자동 gate는 10건 모두 기대 동작 범주였고, 수동 의미
검토의 잠정 결과는 `pass 7 / partial 2 / fail 1`이다.

- 두 visual-only 사례는 잘못된 값 생성에서 source 없는 text-only 거부로 개선됐다.
- 영문 Project plan의 지연 감점 사례는 source recall `0.0 -> 1.0`으로 개선됐고,
  3일 지연 15%와 모델 불일치의 비정량 영향을 구분했다.
- revert/DVCS 사례는 최종 source recall 1.0, AGPL 사례는 strong-copyleft 근거와
  SaaS 조항 부재를 분리해 답했다.
- stash 사례는 `.gitignore` 해제 선행 단계를 여전히 생략해 partial이다.
- RS485 사례는 한 번의 생성에서 `NLNNB`의 두 번째 `L`을 `N`으로 잘못 해석해
  fail이다. 검색 recall은 1.0이므로 생성 정확도 회귀로 분류한다.
- MPL/GPL 사례는 제거·대체 선택지를 생략해 partial이다.

단일 생성 실행은 확률적 안정성을 보장하지 않는다. 위 세 잔여 사례와 직전 pass
사례를 각각 최소 3회 반복한 뒤 Vision 실험의 비교 기준선을 확정한다.

## 2026-08-07 Gemma 4 Vision 기술 검증

현재 12B W4A16 모델은 `Gemma4UnifiedForConditionalGeneration`과
`vision_config`를 포함한다. PDF 19페이지를 1.5배 PNG로 렌더링해 vLLM의
OpenAI 호환 `image_url` 입력으로 질의한 결과, 화면의 문자열을
`LB05-01 NLNNN`으로 정확히 반환했다. 직후 텍스트 요청도 `OK`로 응답했고
엔진과 네 컨테이너가 모두 정상 상태를 유지했다.

최초 요청에서는 vLLM 0.25.0이 양자화된 `ReplicatedLinear`에서 존재하지 않는
`weight.dtype`를 조회해 EngineCore가 종료됐다. custom LLM 이미지에서
projection의 선언 dtype인 `params_dtype`를 사용하도록 보완했고,
`--limit-mm-per-prompt.image 1`을 설정한 뒤 동일 요청으로 재검증했다. 이는 현재
모델로 이미지 입력이 기술적으로 가능하다는 증거이지, 전체 문서군의 Vision
정확도를 보장하는 결과는 아니다.

초기 Vision 도입은 질의 시 모든 페이지 이미지를 넣는 방식보다 수집 시점의 선택적
caption 인덱싱이 적합하다.

1. `visual_heavy`, `mixed`, table/drawing 검출 페이지를 120~160 DPI로 렌더링한다.
2. 동일 Gemma 4에 페이지당 이미지 1장씩 직렬 요청한다.
3. 보이는 텍스트, 표의 행·열, 도형 관계, 값, confidence를 구조화 JSON으로 받는다.
4. 원문 텍스트와 구분된 visual evidence chunk로 저장하고 기존 embedding 흐름에 넣는다.
5. 검색·답변에서는 modality와 page provenance를 유지하고 낮은 confidence는 단정하지 않는다.
6. visual-only fixture를 text-only와 text+vision으로 각각 3회 비교한다.

현재 모델 산출물의 quantization ignore 목록은 `lm_head`뿐이라 vision projection도
W4A16 대상이다. 단일 프로브는 통과했지만 운영용 품질을 위해서는 현재 양자화
스크립트처럼 vision/audio connector를 BF16으로 제외해 다시 내보낸 모델과 정확도,
VRAM, 지연을 비교해야 한다. 또한 같은 GPU에서 embedding, caption, 답변 생성을
동시에 실행하므로 caption 작업은 초기에는 동시성 1의 별도 queue로 제한한다.

## 2026-08-07 Vision caption 인덱싱 구현

문서 처리 경로에 선택적 Vision caption을 연결했다. 운영 기본값은 품질 기준선이
확정될 때까지 `disabled`다. `risk_only`는 text-only가
불완전한 페이지, 검출된 표, 도형이 많은 mixed 페이지를 처리하고 `all_visual`은
시각 요소가 있는 모든 페이지를 처리한다. 테스트 및 retrieval benchmark는 비교
기준을 보존하도록 `disabled`를 명시한다.

페이지는 기본 144 DPI PNG data URL로 일시 렌더링하며 이미지 자체는 DB에 저장하지
않는다. Gemma 4는 summary, visible text, table 관계, diagram 관계, key/value,
limitations와 confidence를 JSON으로 반환한다. 구조화 결과와 모델·caption 버전·상태는
`document_pages.metadata`에 저장하고, 검색용 표현은 기존 `chunks`에
`content_type=vision_caption`으로 추가한다. 원문은 `content_type=text`로 유지하며
두 종류 모두 BGE-M3 텍스트 embedding과 기존 Dense/Keyword/Substring/Hybrid 검색을
사용한다.

Caption 실패는 해당 page metadata에 실패 상태만 기록하고 문서의 text-only
인덱싱을 계속한다. 시각 질문 guard는 같은 페이지의 `vision_caption` chunk가 실제
검색 Context에 있을 때만 시각 근거가 확보된 것으로 판단한다. retrieval trace
schema v3는 후보와 최종 Context의 modality를 기록한다.

실제 Manual 19페이지를 새 서비스 경로로 처리한 결과 JSON 파싱과
`LB05 01 NLNNN` 추출에 성공했고, 동일 페이지에서 `text`, `vision_caption` chunk가
각각 생성됐다. 이 결과는 단일 페이지 기능 검증이며 품질 기준선은 visual-only
fixture를 text-only와 text+vision으로 각 3회 재실행해 확정해야 한다.

추가로 Behavior Modeling II 20페이지 상태 다이어그램을 반복 확인한 결과, 화면
문자열 사례와 달리 JSON 형식 실패, 잘못된 한국어 전사, 관계 누락과 계산값 모순이
발생했다. 모델의 자체 confidence는 이 경우에도 1.0이어서 품질 gate로 사용할 수
없다. JSON Schema 응답 강제로 최신 실행은 repair 없이 유효 JSON을 반환하고
계산 답을 직접 삽입하는 문제는 줄었지만, 한국어 OCR과 표·관계 전사는 여전히
노이즈가 있었다. diagram fixture 반복 평가와 별도 OCR 또는 더 강한 VLM 비교가
끝나기 전에는 `risk_only`를 명시적으로 활성화한 실험 범위로 제한한다.
