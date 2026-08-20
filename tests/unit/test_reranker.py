from dataclasses import dataclass

from app.services import reranker


@dataclass
class _Chunk:
    """임베딩 재정렬 입력으로 쓰는 최소 청크 대역이다."""
    id: int
    content: str
    embedding: list[float]


def _rows():
    """재정렬 검증에 쓸 고정 후보 행을 만든다."""
    return [
        (_Chunk(1, "reset passage", [1.0, 0.0]), 0.9, "reset.pdf"),
        (_Chunk(2, "revert passage", [0.0, 1.0]), 0.8, "revert.pdf"),
        (_Chunk(3, "overall passage", [0.7, 0.7]), 0.7, "overall.pdf"),
    ]


def test_embedding_reranker_uses_bge_query_embeddings(monkeypatch) -> None:
    """BGE 질의 임베딩으로 가장 가까운 후보를 선택하는지 보장한다."""
    class _EmbeddingClient:
        """질의 임베딩 결과를 고정하는 클라이언트 대역이다."""
        def embed_queries(self, texts):
            """입력 질의를 확인하고 대응 임베딩을 반환한다."""
            assert texts == ["reset question"]
            return [[1.0, 0.0]]

    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("reset question", _rows(), top_k=1)

    assert selected[0][0].id == 1


def test_embedding_reranker_preserves_best_candidate_for_each_goal(monkeypatch) -> None:
    """상위 제한 안에서 각 목표의 최적 후보를 모두 보존하는지 보장한다."""
    class _EmbeddingClient:
        """전체 질문과 목표별 질의 임베딩을 제공하는 대역이다."""
        def embed_queries(self, texts):
            """질의 순서를 확인하고 목표별 임베딩을 반환한다."""
            assert texts == ["overall question", "reset query", "revert query"]
            return [[0.7, 0.7], [1.0, 0.0], [0.0, 1.0]]

    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows(
        "overall question",
        _rows(),
        top_k=2,
        queries=["reset query", "revert query"],
        goal_query_groups=(
            ("reset", ("reset query",)),
            ("revert", ("revert query",)),
        ),
    )

    assert {row[0].id for row in selected} == {1, 2}


def test_embedding_failure_preserves_retrieval_rank(monkeypatch) -> None:
    """임베딩 실패 시 검색 순위를 그대로 유지하는지 보장한다."""
    class _FailedClient:
        """임베딩 장애를 발생시키는 클라이언트 대역이다."""
        def embed_queries(self, texts):
            """재정렬의 장애 대체 경로를 위해 오류를 낸다."""
            raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(reranker, "EmbeddingClient", _FailedClient)

    selected = reranker.rerank_rows("question", _rows(), top_k=2)

    assert [row[0].id for row in selected] == [1, 2]
