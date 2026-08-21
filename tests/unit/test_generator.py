from dataclasses import replace

import pytest

from app.clients.llm_client import ContextLengthExceededError, LLMClient
from app.services.evidence_coverage import (
    EvidenceMatrix,
    EvidenceMatrixGoal,
    EvidenceReference,
)
from app.services.generator import INSUFFICIENT_EVIDENCE_ANSWER, generate_answer
from app.services.retriever import RetrievedChunk


@pytest.fixture
def retrieved_chunk() -> RetrievedChunk:
    """답변 생성 검증에 쓸 기본 검색 청크를 제공한다."""
    return RetrievedChunk(
        chunk_id=10,
        document_id=20,
        document_title="lesson.pdf",
        content="낙상 예방 교육 내용",
        page_start=3,
        page_end=3,
        score=0.9,
        source_refs={"page": 3},
    )


def test_generate_answer_removes_sources_and_marker_for_ungrounded_response(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """근거 없음 응답에서 표식과 출처를 모두 제거하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다.",
    )

    generated = generate_answer("자료에 없는 질문", [retrieved_chunk])

    assert generated.answer == "업로드된 자료에서 확인되지 않습니다."
    assert generated.sources == []


def test_generate_answer_supports_legacy_no_source_prefix(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """표식 없는 기존 근거 없음 문구도 출처 없이 처리하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: "업로드된 자료에서 확인되지 않습니다. 질문을 바꿔주세요.",
    )

    generated = generate_answer("자료에 없는 질문", [retrieved_chunk])

    assert generated.sources == []


@pytest.mark.parametrize("marker", ["[[NO_SOURCE]", "[NO_SOURCE]", "[NO_SOURCE]]"])
def test_generate_answer_accepts_malformed_no_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
    marker: str,
) -> None:
    """깨진 근거 없음 표식도 노출하지 않고 인식하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            f"{marker} 업로드된 자료에서 OS의 메모리 관리정책에 대한 내용은 "
            "확인되지 않습니다."
        ),
    )

    generated = generate_answer("OS의 메모리 관리정책은?", [retrieved_chunk])

    assert generated.answer.startswith("업로드된 자료에서")
    assert "NO_SOURCE" not in generated.answer
    assert generated.sources == []


def test_generate_answer_keeps_generic_detail_after_no_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """근거 없음 표식 뒤의 유용한 안내 문구는 보존하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다. "
            "관련 문서를 추가해 주세요."
        ),
    )

    generated = generate_answer("자료에 없는 배포 절차는?", [retrieved_chunk])

    assert "NO_SOURCE" not in generated.answer
    assert "관련 문서를 추가" in generated.answer
    assert generated.sources == []


def test_generate_answer_keeps_sources_for_grounded_response(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """유효하게 인용된 답변은 대응 출처를 유지하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"
        ),
    )

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert generated.answer == "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"
    assert len(generated.sources) == 1
    assert generated.sources[0].document_id == retrieved_chunk.document_id


def test_generate_answer_returns_only_cited_unique_source_pages(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """인용된 문서 페이지만 중복 없이 출처로 반환하는지 보장한다."""
    chunks = [
        retrieved_chunk,
        RetrievedChunk(
            chunk_id=11,
            document_id=30,
            document_title="git.pdf",
            content="Git은 변경 이력을 추적한다.",
            page_start=9,
            page_end=9,
            score=0.8,
            source_refs={"page": 9},
        ),
        RetrievedChunk(
            chunk_id=12,
            document_id=30,
            document_title="git.pdf",
            content="Git은 이전 버전으로 복구할 수 있다.",
            page_start=9,
            page_end=9,
            score=0.7,
            source_refs={"page": 9},
        ),
    ]
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "Git은 변경 이력을 추적합니다. "
            "[Source 2, Page 9; Source 3, Page 9; Source 99, Page 1]"
        ),
    )

    generated = generate_answer("Git의 특성은?", chunks)

    assert len(generated.sources) == 1
    assert generated.sources[0].document_id == 30
    assert generated.sources[0].page == 9
    assert generated.sources[0].chunk_id == 11


def test_generate_answer_keeps_all_sources_used_for_a_derived_conclusion(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """도출 결론에 함께 인용된 모든 근거 출처를 보존하는지 보장한다."""
    reset_chunk = RetrievedChunk(
        chunk_id=21,
        document_id=30,
        document_title="git-history.pdf",
        content="reset은 브랜치가 가리키는 커밋을 이동시켜 이후 이력을 변경한다.",
        page_start=10,
        page_end=10,
        score=0.9,
        source_refs={"page": 10},
    )
    revert_chunk = RetrievedChunk(
        chunk_id=22,
        document_id=30,
        document_title="git-history.pdf",
        content="revert는 기존 변경을 취소하는 새 커밋을 만들어 이전 이력을 보존한다.",
        page_start=11,
        page_end=11,
        score=0.8,
        source_refs={"page": 11},
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "reset은 기존 이력을 변경하지만 revert는 취소 커밋을 추가해 이력을 보존하므로 "
            "공유 이력에는 revert가 적합합니다. "
            "[Source 2, Page 10; Source 3, Page 11]"
        ),
    )

    generated = generate_answer(
        "공유된 커밋에는 왜 revert를 사용하나요?",
        [retrieved_chunk, reset_chunk, revert_chunk],
    )

    assert [source.chunk_id for source in generated.sources] == [21, 22]


def test_generate_answer_does_not_expose_uncited_candidates(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """인용되지 않은 검색 후보를 최종 출처로 노출하지 않는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: "자료에서는 낙상 예방 교육을 시행합니다.",
    )

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert generated.sources == []


def test_generate_answer_blocks_exact_visual_page_request_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """시각 근거 없는 특정 도표 계산 요청을 LLM 호출 전에 차단하는지 보장한다."""
    chunk = RetrievedChunk(
        chunk_id=30,
        document_id=40,
        document_title="diagram.pdf",
        content="e1 e2 e4 e4 e3 e1",
        page_start=20,
        page_end=20,
        score=0.9,
        source_refs={
            "page_metadata": {
                "has_visual_content": True,
                "visual_evidence_risk": "visual_heavy",
            }
        },
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Visual-only request must be blocked locally"),
    )

    generated = generate_answer(
        "20페이지 상태 다이어그램의 최종 값을 계산해 주세요.",
        [chunk],
    )

    assert "시각 근거가 검색되지 않았습니다" in generated.answer
    assert generated.sources == []


def test_generate_answer_requests_detail_when_all_evidence_goals_are_missing(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """모든 근거 목표가 누락되면 답변 대신 구체화 요청을 반환하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Insufficient evidence must not call the answer LLM"),
    )

    generated = generate_answer(
        "rollback 중 꼬이면 어떻게 하나요?",
        [retrieved_chunk],
        evidence_matrix=EvidenceMatrix(
            status="insufficient",
            goals=(
                EvidenceMatrixGoal("g1", "현재 상태별 안전한 복구 절차", "missing"),
            ),
        ),
    )

    assert generated.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert "사용한 명령" in generated.answer
    assert "발생한 오류" in generated.answer
    assert "현재 상태" in generated.answer
    assert "되돌릴 대상" in generated.answer
    assert generated.sources == []


def test_generate_answer_allows_explicitly_requested_qualified_answer(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """사용자가 요구한 조건부 답변은 근거 부족 상태에서도 허용하는지 보장한다."""
    captured: list[list[dict[str, str]]] = []

    def answer(_, messages, **kwargs):
        """전달된 프롬프트를 기록하고 인용된 조건부 답변을 반환한다."""
        captured.append(messages)
        return "자료가 확인하는 일반 원칙만 설명합니다. [Source 1, Page 3]"

    monkeypatch.setattr(LLMClient, "chat_completion", answer)

    generated = generate_answer(
        "자료가 뒷받침하는 내용과 확정할 수 없는 부분을 구분해 주세요.",
        [retrieved_chunk],
        evidence_matrix=EvidenceMatrix(
            status="insufficient",
            goals=(EvidenceMatrixGoal("g1", "구체 적용 조건", "missing"),),
        ),
    )

    assert "일반 원칙" in generated.answer
    assert len(generated.sources) == 1
    assert "Coverage: INSUFFICIENT" in captured[0][-1]["content"]
    assert "GOAL g1 [MISSING]: 구체 적용 조건" in captured[0][-1]["content"]


def test_generate_answer_restores_confusable_question_literal_without_rewriting_other_codes(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """혼동된 질문 리터럴만 복원하고 다른 코드는 보존하는지 보장한다."""
    operations: list[str] = []

    def complete(*args, **kwargs):
        """생성 및 리터럴 복구 단계별 응답을 제공한다."""
        operation = kwargs["operation"]
        operations.append(operation)
        if operation == "answer":
            return (
                "IB05 03 NLNNB의 상태는 LBN입니다. 채널 2는 Normal입니다. "
                "LB05 01 NLNNN은 비교 예시입니다. [Source 1, Page 3]"
            )
        if operations.count("literal_fidelity_repair") == 1:
            return (
                "LB05 03 NLNNB에서 LBN에서 각 위치를 설명합니다. "
                "채널 2는 L (Leak)입니다. [Source 1, Page 3]"
            )
        return (
            "LB05 03 NLNNB의 상태는 NLNNB입니다. 채널 2는 Leak입니다. "
            "LB05 01 NLNNN은 비교 예시입니다. [Source 1, Page 3]"
        )

    monkeypatch.setattr(LLMClient, "chat_completion", complete)
    monkeypatch.setattr(
        "app.services.generator.validate_answer_citations",
        lambda question, answer, chunks: answer,
    )

    generated = generate_answer(
        "`LB05 03 NLNNB`의 채널 1~5를 위치별로 해석해 주세요.",
        [retrieved_chunk],
    )

    assert "IB05 03 NLNNB" not in generated.answer
    assert "LB05 03 NLNNB" in generated.answer
    assert "LB05 01 NLNNN" in generated.answer
    assert "상태는 NLNNB" in generated.answer
    assert "채널 2는 Leak" in generated.answer
    assert operations == ["answer", "literal_fidelity_repair", "literal_fidelity_repair"]


def test_generate_answer_normalizes_positional_channel_mapping_from_context(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """문맥의 채널 정의에 맞춰 위치별 코드 해석을 교정하는지 보장한다."""
    retrieved_chunk = replace(
        retrieved_chunk,
        content=(
            "1번 채널 정상-Normal, 2번 채널 감지-Leak, "
            "3번 채널 정상-Normal, 4번 채널 정상-Normal, "
            "5번 채널 단선-Broken 의미"
        ),
    )
    wrong_answer = (
        "**1. 채4널별 상태 해석**\n"
        "`LBN`에서 각 위치를 해석합니다.\n"
        "* **채널 1**: N (Normal) [Source 1, Page 3]\n"
        "* **채널 2**: N (Normal) [Source 1, Page 3]\n"
        "* **채널 3**: N (Normal) [Source 1, Page 3]\n"
        "* **채널 4**: N (Normal) [Source 1, Page 3]\n"
        "* **채널 5**: B (Broken) [Source 1, Page 3]\n"
        "**2. 통신 조건**\nCR과 50ms가 필요합니다. [Source 1, Page 3]"
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: wrong_answer,
    )
    monkeypatch.setattr(
        "app.services.generator.validate_answer_citations",
        lambda question, answer, chunks: answer,
    )

    generated = generate_answer(
        "`LB05 03 NLNNB`의 채널 1~5를 위치별로 해석해 주세요.",
        [retrieved_chunk],
    )

    assert "`NLNNB`에서 각 위치" in generated.answer
    assert "**채널 2**: L (감지 / Leak)" in generated.answer
    assert "**채널 5**: B (단선 / Broken)" in generated.answer
    assert "`LBN`" not in generated.answer
    assert "채4널" not in generated.answer
    assert "**2. 통신 조건**" in generated.answer


def test_generate_answer_prepends_missing_exclusion_release_step(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """제외 파일 작업 답변 앞에 제외 해제 단계를 추가하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: "파일을 git add한 뒤 stash합니다.",
    )

    generated = generate_answer(
        "secret.txt를 .gitignore에 넣었는데 stash하려면 어떻게 하나요?",
        [retrieved_chunk],
    )

    assert generated.answer.startswith(
        "먼저 질문에 명시된 제외·무시 상태를 해제해야 합니다."
    )
    assert "git add한 뒤 stash" in generated.answer


def test_generate_answer_retries_degenerate_repetition_once(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """퇴행적 반복 응답을 감지해 정확히 한 번 재생성하는지 보장한다."""
    responses = iter(
        [
            "낙상 예방은 t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.",
            "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]",
        ]
    )
    operations: list[str] = []

    def complete(self, messages, **kwargs):
        """호출 작업을 기록하고 순서대로 준비된 응답을 반환한다."""
        operations.append(kwargs["operation"])
        return next(responses)

    monkeypatch.setattr(LLMClient, "chat_completion", complete)

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert operations == ["answer", "answer_retry"]
    assert "t.t.t" not in generated.answer
    assert len(generated.sources) == 1


def test_generate_answer_maps_citations_to_prioritized_bounded_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """우선순위와 길이 제한이 적용된 문맥 기준으로 인용을 매핑하는지 보장한다."""
    chunks = [
        RetrievedChunk(
            chunk_id=index,
            document_id=20 + index,
            document_title=f"document-{index}.pdf",
            content=f"핵심 근거 {index} " + ("x" * 4000),
            page_start=index,
            page_end=index,
            score=1.0 - index / 10,
            source_refs={"page": index},
        )
        for index in range(1, 6)
    ]
    matrix = EvidenceMatrix(
        status="complete",
        goals=(
            EvidenceMatrixGoal(
                "g1",
                "후순위 핵심 근거",
                "supported",
                (EvidenceReference(5, "document-5.pdf", 5, 5),),
            ),
        ),
    )
    captured_messages: list[dict[str, str]] = []

    def complete(self, messages, **kwargs):
        """생성 메시지를 기록하고 첫 문맥 근거를 인용한다."""
        captured_messages.extend(messages)
        return "후순위 핵심 근거입니다. [Source 1, Page 5]"

    monkeypatch.setattr(LLMClient, "chat_completion", complete)

    generated = generate_answer("핵심 근거는?", chunks, evidence_matrix=matrix)

    assert "[Source 1]\nDocument: document-5.pdf" in captured_messages[-1]["content"]
    assert generated.sources[0].chunk_id == 5


def test_generate_answer_retries_with_compact_context_after_overflow(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """일반 입력 초과 뒤 더 짧은 근거와 이력으로 답변 생성을 복구한다."""
    calls: list[list[dict[str, str]]] = []

    def complete(self, messages, **kwargs):
        """첫 입력만 거부하고 축소 입력에는 근거 답변을 반환한다."""
        calls.append(messages)
        if len(calls) == 1:
            raise ContextLengthExceededError("context overflow")
        return "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"

    monkeypatch.setattr(LLMClient, "chat_completion", complete)
    long_chunk = replace(retrieved_chunk, content="낙상 예방 근거 " * 1200)
    history = [
        {"role": "user", "content": "가" * 4000},
        {"role": "assistant", "content": "나" * 4000},
    ]

    generated = generate_answer(
        "낙상 예방은?",
        [long_chunk],
        history=history,
    )

    assert len(calls) == 2
    assert sum(len(message["content"]) for message in calls[1]) < sum(
        len(message["content"]) for message in calls[0]
    )
    assert generated.answer.endswith("[Source 1, Page 3]")
    assert [source.chunk_id for source in generated.sources] == [retrieved_chunk.chunk_id]


def test_generate_answer_returns_extractive_evidence_when_every_attempt_overflows(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """모든 생성 입력이 초과해도 검색 근거와 출처가 있는 정상 응답을 반환한다."""
    calls = 0

    def overflow(self, messages, **kwargs):
        """모든 생성 단계에서 컨텍스트 초과를 반환한다."""
        nonlocal calls
        calls += 1
        raise ContextLengthExceededError("context overflow")

    monkeypatch.setattr(LLMClient, "chat_completion", overflow)

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert calls == 3
    assert "검색된 핵심 근거" in generated.answer
    assert "낙상 예방 교육 내용" in generated.answer
    assert "[Source 1, Page 3]" in generated.answer
    assert [source.chunk_id for source in generated.sources] == [retrieved_chunk.chunk_id]


def test_generate_answer_does_not_hide_non_context_failures(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """서비스 장애는 근거 발췌로 가장하지 않고 기존 오류 경로로 전달한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("service unavailable")),
    )

    with pytest.raises(RuntimeError, match="service unavailable"):
        generate_answer("낙상 예방은?", [retrieved_chunk])
