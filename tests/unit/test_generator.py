import pytest

from app.clients.vllm_client import VLLMClient
from app.services.generator import generate_answer
from app.services.retriever import RetrievedChunk


@pytest.fixture
def retrieved_chunk() -> RetrievedChunk:
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
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages: "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다.",
    )

    generated = generate_answer("자료에 없는 질문", [retrieved_chunk])

    assert generated.answer == "업로드된 자료에서 확인되지 않습니다."
    assert generated.sources == []


def test_generate_answer_supports_legacy_no_source_prefix(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages: "업로드된 자료에서 확인되지 않습니다. 질문을 바꿔주세요.",
    )

    generated = generate_answer("자료에 없는 질문", [retrieved_chunk])

    assert generated.sources == []


def test_generate_answer_accepts_malformed_no_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages: (
            "[[NO_SOURCE] 업로드된 자료에서 OS의 메모리 관리정책에 대한 내용은 "
            "확인되지 않습니다."
        ),
    )

    generated = generate_answer("OS의 메모리 관리정책은?", [retrieved_chunk])

    assert generated.answer.startswith("업로드된 자료에서")
    assert "NO_SOURCE" not in generated.answer
    assert generated.sources == []


def test_generate_answer_keeps_safety_guidance_after_no_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다. "
            "실제 환자라면 즉시 의료진에게 문의하세요."
        ),
    )

    generated = generate_answer("실제 환자의 처치는?", [retrieved_chunk])

    assert "NO_SOURCE" not in generated.answer
    assert "의료진" in generated.answer
    assert generated.sources == []


def test_generate_answer_keeps_sources_for_grounded_response(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages: "자료에서는 낙상 예방 교육을 시행합니다.",
    )

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert generated.answer == "자료에서는 낙상 예방 교육을 시행합니다."
    assert len(generated.sources) == 1
    assert generated.sources[0].document_id == retrieved_chunk.document_id
