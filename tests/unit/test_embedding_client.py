from app.clients.embedding_client import EmbeddingClient


class _Response:
    """임베딩 서비스 응답 형식만 제공하는 테스트 대역이다."""
    def __init__(self, texts: list[str]) -> None:
        """요청 문장을 응답 벡터 생성에 보관한다."""
        self._texts = texts

    def raise_for_status(self) -> None:
        """성공 응답처럼 HTTP 오류 검사를 통과한다."""
        return None

    def json(self) -> dict:
        """문장 길이로 결정되는 임베딩 응답을 반환한다."""
        return {"embeddings": [[float(len(text))] for text in self._texts]}


def test_embed_queries_batches_service_limit(monkeypatch) -> None:
    """질의 임베딩 요청은 서비스의 배치 한도를 넘지 않게 나뉜다."""
    batches: list[list[str]] = []

    def post(url, json, timeout):
        """전송된 배치를 기록하고 해당 배치의 응답을 돌려준다."""
        batches.append(json["texts"])
        return _Response(json["texts"])

    monkeypatch.setattr("app.clients.embedding_client.httpx.post", post)
    texts = [f"query-{index}" for index in range(12)]

    embeddings = EmbeddingClient(base_url="http://embedding").embed_queries(texts)

    assert [len(batch) for batch in batches] == [5, 5, 2]
    assert len(embeddings) == len(texts)
