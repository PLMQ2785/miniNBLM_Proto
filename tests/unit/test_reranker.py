from dataclasses import dataclass

from app.services import reranker


@dataclass
class _Chunk:
    id: int
    content: str
    embedding: list[float]


def _rows():
    return [
        (_Chunk(1, "reset passage", [1.0, 0.0]), 0.9, "reset.pdf"),
        (_Chunk(2, "revert passage", [0.0, 1.0]), 0.8, "revert.pdf"),
        (_Chunk(3, "overall passage", [0.7, 0.7]), 0.7, "overall.pdf"),
    ]


def test_embedding_reranker_uses_bge_query_embeddings(monkeypatch) -> None:
    class _EmbeddingClient:
        def embed_queries(self, texts):
            assert texts == ["reset question"]
            return [[1.0, 0.0]]

    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("reset question", _rows(), top_k=1)

    assert selected[0][0].id == 1


def test_embedding_reranker_preserves_best_candidate_for_each_goal(monkeypatch) -> None:
    class _EmbeddingClient:
        def embed_queries(self, texts):
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
    class _FailedClient:
        def embed_queries(self, texts):
            raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(reranker, "EmbeddingClient", _FailedClient)

    selected = reranker.rerank_rows("question", _rows(), top_k=2)

    assert [row[0].id for row in selected] == [1, 2]
