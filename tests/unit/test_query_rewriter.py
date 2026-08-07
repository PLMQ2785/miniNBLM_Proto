import pytest

from app.clients.vllm_client import VLLMClient
from app.services.query_rewriter import plan_retrieval_queries, rewrite_retrieval_query


def test_single_hop_question_produces_one_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            '{"standalone_query":"낙상 예방 방법은?",'
            '"queries":["낙상 예방 방법은?"]}'
        ),
    )

    plan = plan_retrieval_queries("낙상 예방 방법은?", [])

    assert plan.standalone_query == "낙상 예방 방법은?"
    assert plan.queries == ("낙상 예방 방법은?",)


def test_tagged_multi_hop_plan_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: """STANDALONE: push된 커밋에서 revert를 사용하는 이유
QUERY: git reset hard 이력 변경 특성
QUERY: git revert 역커밋 생성 특성
QUERY: 원격 저장소 공유 이력 협업""",
    )

    plan = plan_retrieval_queries("복합 질문", [])

    assert plan.standalone_query == "push된 커밋에서 revert를 사용하는 이유"
    assert plan.queries == (
        "push된 커밋에서 revert를 사용하는 이유",
        "git reset hard 이력 변경 특성",
        "git revert 역커밋 생성 특성",
        "원격 저장소 공유 이력 협업",
    )


def test_multi_hop_question_is_decomposed_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: """```json
        {
          "standalone_query": "push된 커밋에서 reset 대신 revert를 사용해야 하는 이유",
          "queries": [
            "push된 커밋에서 reset 대신 revert를 사용해야 하는 이유",
            "git reset hard 이력 변경 특성",
            "git revert 역커밋 생성 특성",
            "원격 저장소 공유 이력 협업",
            "제한을 초과해 제외될 질의"
          ]
        }
        ```""",
    )

    plan = plan_retrieval_queries("복합 질문", [])

    assert plan.standalone_query == "push된 커밋에서 reset 대신 revert를 사용해야 하는 이유"
    assert plan.queries == (
        "push된 커밋에서 reset 대신 revert를 사용해야 하는 이유",
        "git reset hard 이력 변경 특성",
        "git revert 역커밋 생성 특성",
        "원격 저장소 공유 이력 협업",
    )


def test_follow_up_is_rewritten_from_the_latest_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    call: dict = {}

    def rewrite(self, messages, temperature=0.2, operation="completion"):
        call["messages"] = messages
        call["temperature"] = temperature
        call["operation"] = operation
        return (
            '{"standalone_query":"낙상 후 손상 여부 확인 다음 조치",'
            '"queries":["낙상 후 손상 여부 확인 다음 조치"]}'
        )

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
        return '{"standalone_query":"독립 질문","queries":["독립 질문"]}'

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


def test_invalid_json_falls_back_to_a_single_normalized_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "검색 질의: git revert 협업 특성",
    )

    plan = plan_retrieval_queries("원래 질문", [])

    assert plan.standalone_query == "git revert 협업 특성"
    assert plan.queries == ("git revert 협업 특성",)


def test_multiple_json_objects_select_the_plan_with_more_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: """
        {"standalone_query":"전체 질문","queries":[]}
        설명을 덧붙였습니다.
        {"standalone_query":"전체 질문","queries":["근거 A","근거 B"]}
        """,
    )

    plan = plan_retrieval_queries("원래 질문", [])

    assert plan.standalone_query == "전체 질문"
    assert plan.queries == ("전체 질문", "근거 A", "근거 B")


def test_malformed_structured_response_falls_back_to_original_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: '{"standalone_query":"잘린 응답", "queries":[',
    )

    plan = plan_retrieval_queries("원래 질문", [])

    assert plan.standalone_query == "원래 질문"
    assert plan.queries == ("원래 질문",)
