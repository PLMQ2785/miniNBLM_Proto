import pytest

from app.clients.embedding_client import EmbeddingClient
from app.clients.reranker_client import RerankerClient


class _Response:
    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"embeddings": [[float(len(text))] for text in self._texts]}


def test_embed_queries_batches_service_limit(monkeypatch) -> None:
    batches: list[list[str]] = []

    def post(url, json, timeout):
        batches.append(json["texts"])
        return _Response(json["texts"])

    monkeypatch.setattr("app.clients.embedding_client.httpx.post", post)
    texts = [f"query-{index}" for index in range(12)]

    embeddings = EmbeddingClient(base_url="http://embedding").embed_queries(texts)

    assert [len(batch) for batch in batches] == [5, 5, 2]
    assert len(embeddings) == len(texts)


def test_reranker_client_batches_pairs_and_preserves_score_order(monkeypatch) -> None:
    batches: list[list[dict[str, str]]] = []

    class _RerankResponse:
        def __init__(self, pairs: list[dict[str, str]]) -> None:
            self._pairs = pairs

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"scores": [float(len(pair["passage"])) for pair in self._pairs]}

    def post(url, json, timeout):
        assert url == "http://embedding/rerank"
        batches.append(json["pairs"])
        return _RerankResponse(json["pairs"])

    monkeypatch.setattr("app.clients.reranker_client.MAX_RERANK_BATCH_SIZE", 2)
    monkeypatch.setattr("app.clients.reranker_client.httpx.post", post)
    pairs = [(f"query-{index}", "x" * index) for index in range(1, 6)]

    scores = RerankerClient(base_url="http://embedding").score_pairs(pairs)

    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert scores == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_reranker_client_rejects_wrong_score_count(monkeypatch) -> None:
    class _InvalidResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"scores": []}

    monkeypatch.setattr(
        "app.clients.reranker_client.httpx.post",
        lambda *args, **kwargs: _InvalidResponse(),
    )

    with pytest.raises(ValueError, match="invalid score count"):
        RerankerClient(base_url="http://embedding").score_pairs([("query", "passage")])
