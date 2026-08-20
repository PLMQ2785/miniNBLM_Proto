from dataclasses import dataclass

import pytest

from app.clients.embedding_client import EmbeddingClient
from app.services.reranker import rerank_rows
from app.services.retriever import _merge_query_anchors, _reciprocal_rank_fusion


@dataclass(frozen=True)
class StubChunk:
    """검색 융합과 재정렬 입력을 단순화한 청크 대역이다."""
    id: int
    embedding: list[float] | None = None


def test_reciprocal_rank_fusion_combines_and_deduplicates_results() -> None:
    """상호 순위 융합이 중복을 제거하고 누적 순위로 정렬하는지 보장한다."""
    first = StubChunk(1)
    second = StubChunk(2)
    third = StubChunk(3)

    rows = _reciprocal_rank_fusion(
        (
            [(first, 0.1, "first.pdf"), (second, 0.2, "second.pdf")],
            [(second, 0.9, "second.pdf"), (third, 0.8, "third.pdf")],
            [(second, 0.7, "second.pdf"), (first, 0.6, "first.pdf")],
        ),
        top_k=2,
    )

    assert [chunk.id for chunk, _, _ in rows] == [2, 1]
    assert rows[0][1] > rows[1][1]
    assert [title for _, _, title in rows] == ["second.pdf", "first.pdf"]


def test_reciprocal_rank_fusion_handles_empty_sources() -> None:
    """빈 검색 결과 묶음이 빈 융합 결과를 내는지 보장한다."""
    assert _reciprocal_rank_fusion(([], []), top_k=3) == []


def test_multi_query_fusion_preserves_each_query_top_candidate() -> None:
    """다중 질의 병합이 각 질의의 최상위 후보를 보존하는지 보장한다."""
    shared = StubChunk(1)
    first_facet = StubChunk(2)
    second_facet = StubChunk(3)
    result_sets = [
        [(first_facet, 0.9, "first.pdf"), (shared, 0.8, "shared.pdf")],
        [(second_facet, 0.9, "second.pdf"), (shared, 0.8, "shared.pdf")],
    ]
    fused = [(shared, 1.0, "shared.pdf"), (first_facet, 0.5, "first.pdf")]

    rows = _merge_query_anchors(result_sets, fused, limit=2)

    assert [chunk.id for chunk, _, _ in rows] == [2, 3]


def test_semantic_reranker_promotes_candidate_matching_the_original_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """의미 재정렬이 원 질문과 가까운 후보를 우선하는지 보장한다."""
    lexical_first = StubChunk(1, [0.0, 1.0])
    semantic_match = StubChunk(2, [1.0, 0.0])
    monkeypatch.setattr(
        EmbeddingClient,
        "embed_query",
        lambda self, question: [1.0, 0.0],
    )

    rows = rerank_rows(
        "original question",
        [
            (lexical_first, 0.9, "lexical.pdf"),
            (semantic_match, 0.5, "semantic.pdf"),
        ],
        top_k=2,
    )

    assert [chunk.id for chunk, _, _ in rows] == [2, 1]
    assert rows[0][1] > rows[1][1]


def test_semantic_reranker_falls_back_to_retrieval_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """임베딩 실패 시 기존 검색 순위로 안전하게 대체하는지 보장한다."""
    first = StubChunk(1, [1.0, 0.0])
    second = StubChunk(2, [0.0, 1.0])

    def fail(*args, **kwargs):
        """임베딩 서비스 장애를 재현한다."""
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(EmbeddingClient, "embed_query", fail)

    rows = rerank_rows(
        "original question",
        [(first, 0.9, "first.pdf"), (second, 0.8, "second.pdf")],
        top_k=1,
    )

    assert rows == [(first, 0.9, "first.pdf")]


def test_semantic_reranker_preserves_the_best_candidate_for_each_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """제한된 결과에서도 각 근거 목표의 최상위 후보를 보존하는지 보장한다."""
    overall = StubChunk(1, [1.0, 0.0, 0.0])
    reset = StubChunk(2, [0.0, 1.0, 0.0])
    collaboration = StubChunk(3, [0.0, 0.0, 1.0])
    monkeypatch.setattr(
        EmbeddingClient,
        "embed_queries",
        lambda self, texts: [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
    )

    rows = rerank_rows(
        "overall question",
        [
            (overall, 0.9, "overall.pdf"),
            (reset, 0.8, "reset.pdf"),
            (collaboration, 0.7, "collaboration.pdf"),
        ],
        top_k=2,
        queries=("reset history", "distributed collaboration"),
        goal_query_groups=(
            ("reset", ("reset history",)),
            ("collaboration", ("distributed collaboration",)),
        ),
    )

    assert {chunk.id for chunk, _, _ in rows} == {2, 3}
