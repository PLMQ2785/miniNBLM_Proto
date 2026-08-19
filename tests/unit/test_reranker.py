from dataclasses import dataclass

from app.services import reranker


@dataclass
class _Chunk:
    id: int
    content: str
    embedding: list[float]


def _rows():
    return [
        (_Chunk(1, "facet passage", [1.0, 0.0]), 0.9, "doc"),
        (_Chunk(2, "original passage", [0.0, 1.0]), 0.8, "doc"),
        (_Chunk(3, "unrelated passage", [0.5, 0.5]), 0.7, "doc"),
    ]


def test_cross_encoder_reranker_preserves_facet_anchor(monkeypatch) -> None:
    captured_pairs: list[tuple[str, str]] = []

    class _Client:
        def score_pairs(self, pairs):
            captured_pairs.extend(pairs)
            return [0.1, 0.9, 0.2, 0.95, 0.1, 0.2]

    monkeypatch.setattr(reranker.settings, "reranker_mode", "cross_encoder")
    monkeypatch.setattr(reranker, "RerankerClient", _Client)

    selected = reranker.rerank_rows(
        "original question",
        _rows(),
        top_k=2,
        queries=["facet question"],
    )

    assert captured_pairs == [
        ("original question", "facet passage"),
        ("original question", "original passage"),
        ("original question", "unrelated passage"),
        ("facet question", "facet passage"),
        ("facet question", "original passage"),
        ("facet question", "unrelated passage"),
    ]
    assert [row[0].id for row in selected] == [2, 1]


def test_cross_encoder_failure_falls_back_to_embedding_reranker(monkeypatch) -> None:
    class _FailedClient:
        def score_pairs(self, pairs):
            raise RuntimeError("reranker unavailable")

    class _EmbeddingClient:
        def embed_queries(self, texts):
            return [[0.0, 1.0] for _ in texts]

    monkeypatch.setattr(reranker.settings, "reranker_mode", "cross_encoder")
    monkeypatch.setattr(reranker, "RerankerClient", _FailedClient)
    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("question", _rows(), top_k=1)

    assert selected[0][0].id == 2


def test_embedding_mode_does_not_call_cross_encoder(monkeypatch) -> None:
    class _UnexpectedClient:
        def __init__(self):
            raise AssertionError("cross-encoder must not be created")

    class _EmbeddingClient:
        def embed_queries(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(reranker.settings, "reranker_mode", "embedding")
    monkeypatch.setattr(reranker, "RerankerClient", _UnexpectedClient)
    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("question", _rows(), top_k=1)

    assert selected[0][0].id == 1
