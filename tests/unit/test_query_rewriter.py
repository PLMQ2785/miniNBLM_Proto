import json

import pytest

from app.clients.llm_client import LLMClient
from app.services.query_rewriter import plan_retrieval_queries, rewrite_retrieval_query


def _plan_payload(*goals: dict, standalone: str = "독립 질문") -> str:
    return json.dumps(
        {"standalone_query": standalone, "evidence_goals": list(goals)},
        ensure_ascii=False,
    )


def _goal(goal_id: str, description: str, *queries: str) -> dict:
    return {"goal_id": goal_id, "description": description, "queries": list(queries)}


def test_single_hop_question_produces_one_structured_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: _plan_payload(
            _goal("g1", "낙상 예방 방법", "낙상 예방 방법은?"),
            standalone="낙상 예방 방법은?",
        ),
    )

    plan = plan_retrieval_queries("낙상 예방 방법은?", [])

    assert plan.standalone_query == "낙상 예방 방법은?"
    assert plan.goals[0].goal_id == "g1"
    assert plan.goals[0].description == "낙상 예방 방법"
    assert plan.queries == ("낙상 예방 방법은?",)


def test_multi_hop_plan_keeps_unique_goal_ids_and_fair_query_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _plan_payload(
        _goal("g1", "reset 특성", "reset history", "reset shared", "reset danger"),
        _goal("g2", "revert 특성", "revert commit", "revert inverse", "revert safe"),
        _goal("g3", "협업 영향", "shared history", "remote collaboration"),
        _goal("g4", "복구 절차", "restore procedure", "recovery check"),
        standalone="push된 커밋에서 reset 대신 revert를 쓰는 이유",
    )
    monkeypatch.setattr(LLMClient, "chat_completion", lambda *args, **kwargs: payload)

    plan = plan_retrieval_queries("복합 질문", [])

    assert tuple(goal.goal_id for goal in plan.goals) == ("g1", "g2", "g3", "g4")
    assert all(goal.queries for goal in plan.goals)
    assert plan.goals[0].queries == ("reset history", "reset shared")
    assert plan.goals[1].queries == ("revert commit",)
    assert len(plan.queries) == 6


def test_follow_up_uses_only_bounded_latest_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call: dict = {}

    def rewrite(self, messages, **kwargs):
        call.update(messages=messages, kwargs=kwargs)
        return _plan_payload(
            _goal("g1", "다음 조치", "낙상 후 다음 조치"),
            standalone="낙상 후 손상 여부 확인 다음 조치",
        )

    monkeypatch.setattr(LLMClient, "chat_completion", rewrite)
    history = [
        {"role": "user", "content": "무시할 질문"},
        {"role": "assistant", "content": "무시할 답변"},
        {"role": "user", "content": "가" * 700},
        {"role": "assistant", "content": "나" * 1300},
    ]

    result = rewrite_retrieval_query("그 다음에는?", history)

    assert result == "낙상 후 손상 여부 확인 다음 조치"
    assert [message["role"] for message in call["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert len(call["messages"][1]["content"]) == 500
    assert len(call["messages"][2]["content"]) == 1000
    assert call["kwargs"]["response_format"] == {"type": "json_object"}


def test_malformed_plan_is_repaired_once_with_previous_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def rewrite(self, messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if len(calls) == 1:
            return '{"standalone_query":"잘린 응답","evidence_goals":['
        return _plan_payload(
            _goal("stash", "변경 임시 보관", "git stash"),
            _goal("restore", "작업 복원", "git stash pop"),
            standalone="기능 브랜치 변경을 보관한 뒤 복원",
        )

    monkeypatch.setattr(LLMClient, "chat_completion", rewrite)
    history = [
        {"role": "user", "content": "기능 작업 중 긴급 수정 요청"},
        {"role": "assistant", "content": "hotfix 브랜치를 사용합니다"},
    ]

    plan = plan_retrieval_queries("변경을 잃지 않고 복원하려면?", history)

    assert len(calls) == 2
    assert calls[1]["operation"] == "query_rewrite_repair"
    assert "기능 작업 중 긴급 수정 요청" in calls[1]["messages"][-1]["content"]
    assert tuple(goal.goal_id for goal in plan.goals) == ("stash", "restore")


def test_duplicate_goal_id_repair_failure_uses_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = _plan_payload(
        _goal("g1", "첫 목표", "첫 질의"),
        _goal("g1", "둘째 목표", "둘째 질의"),
    )
    monkeypatch.setattr(LLMClient, "chat_completion", lambda *args, **kwargs: invalid)

    plan = plan_retrieval_queries("원래 질문", [])

    assert plan.standalone_query == "원래 질문"
    assert plan.goals[0].goal_id == "g1"
    assert plan.goals[0].queries == ("원래 질문",)


def test_multiple_json_objects_selects_more_complete_structured_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = "\n".join(
        [
            _plan_payload(_goal("g1", "근거 A", "질의 A"), standalone="전체 질문"),
            "설명",
            _plan_payload(
                _goal("g1", "근거 A", "질의 A"),
                _goal("g2", "근거 B", "질의 B"),
                standalone="전체 질문",
            ),
        ]
    )
    monkeypatch.setattr(LLMClient, "chat_completion", lambda *args, **kwargs: response)

    plan = plan_retrieval_queries("원래 질문", [])

    assert plan.standalone_query == "전체 질문"
    assert tuple(goal.goal_id for goal in plan.goals) == ("g1", "g2")


def test_corrupted_goal_keys_are_salvaged_without_format_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    response = json.dumps(
        {
            "standalone_query": "전체 질문",
            "evidence_goals": [
                {
                    "goal_id": "g1",
                    "description": "첫 근거",
                    "queries queries": ["첫 질의"],
                },
                {
                    "goal_2": "g2",
                    "description": "둘째 근거",
                    "queries": ["둘째 질의"],
                },
                {
                    "goal_3": {
                        "goal_id": "g3",
                        "description": "셋째 근거",
                        "queries": ["셋째 질의"],
                    }
                },
                {
                    "goal_id": "g4",
                    "description, ": ["손상된 설명"],
                    "queries geese": ["넷째 질의"],
                },
            ],
        },
        ensure_ascii=False,
    )

    def rewrite(*args, **kwargs):
        nonlocal calls
        calls += 1
        return response

    monkeypatch.setattr(LLMClient, "chat_completion", rewrite)

    plan = plan_retrieval_queries("원래 질문", [])

    assert calls == 1
    assert tuple(goal.goal_id for goal in plan.goals) == ("g1", "g2", "g3", "g4")
    assert tuple(goal.queries[0] for goal in plan.goals) == (
        "첫 질의",
        "둘째 질의",
        "셋째 질의",
        "넷째 질의",
    )
    assert plan.goals[3].description == "넷째 질의"


def test_plain_text_fallback_is_normalized_after_failed_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: "standalone query: 독립형 검색 질문",
    )

    plan = plan_retrieval_queries("원래 질문", [])

    assert plan.standalone_query == "독립형 검색 질문"
    assert plan.goals[0].description == "독립형 검색 질문"


def test_llm_failure_falls_back_to_original_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(LLMClient, "chat_completion", fail)

    plan = plan_retrieval_queries("  원래 질문  ", [])

    assert plan.standalone_query == "원래 질문"
    assert plan.queries == ("원래 질문",)
