from app.clients.embedding_client import EmbeddingClient


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
