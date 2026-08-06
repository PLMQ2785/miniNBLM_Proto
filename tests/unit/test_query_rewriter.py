import pytest

from app.clients.vllm_client import VLLMClient
from app.services.query_rewriter import rewrite_retrieval_query


def test_first_question_is_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("The LLM must not be called without history"),
    )

    assert rewrite_retrieval_query("낙상 예방 방법은?", []) == "낙상 예방 방법은?"


def test_follow_up_is_rewritten_from_the_latest_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    call: dict = {}

    def rewrite(self, messages, temperature=0.2, operation="completion"):
        call["messages"] = messages
        call["temperature"] = temperature
        call["operation"] = operation
        return "검색 질의: 낙상 후 손상 여부 확인 다음 조치"

    monkeypatch.setattr(VLLMClient, "chat_completion", rewrite)
    history = [
        {"role": "user", "content": "이전 주제"},
        {"role": "assistant", "content": "이전 답변"},
        {"role": "user", "content": "낙상 후 무엇을 먼저 하나요?"},
        {"role": "assistant", "content": "손상 여부를 먼저 확인합니다."},
    ]

    result = rewrite_retrieval_query("그 다음에는 무엇을 하나요?", history)

    assert result == "낙상 후 손상 여부 확인 다음 조치"
    assert call["temperature"] == 0.0
    assert call["operation"] == "query_rewrite"
    assert call["messages"][1:3] == history[-2:]
    assert "그 다음에는 무엇을 하나요?" in call["messages"][-1]["content"]


def test_rewrite_uses_bounded_previous_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    call: dict = {}

    def rewrite(self, messages, temperature=0.2, operation="completion"):
        call["messages"] = messages
        return "독립 질문"

    monkeypatch.setattr(VLLMClient, "chat_completion", rewrite)
    history = [
        {"role": "user", "content": "가" * 700},
        {"role": "assistant", "content": "나" * 1300},
    ]

    rewrite_retrieval_query("그 이유는?", history)

    assert len(call["messages"][1]["content"]) == 500
    assert len(call["messages"][2]["content"]) == 1000


def test_rewrite_failure_falls_back_to_original_question(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(VLLMClient, "chat_completion", fail)

    assert rewrite_retrieval_query(
        "  그 다음에는?  ",
        [{"role": "user", "content": "낙상 후 조치는?"}],
    ) == "그 다음에는?"
