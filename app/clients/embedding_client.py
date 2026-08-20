import httpx

from app.config import settings


MAX_QUERY_BATCH_SIZE = 5


class EmbeddingClient:
    """검색과 재순위화에 쓰는 임베딩 서버 호출을 묶는다."""
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        """설정된 임베딩 서버와 요청 제한 시간을 보관한다."""
        self.base_url = (base_url or settings.embedding_base_url).rstrip("/")
        self.timeout = timeout

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """문서 청크를 색인용 벡터로 변환한다."""
        response = httpx.post(
            f"{self.base_url}/embed/documents",
            json={"texts": texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["embeddings"]

    def embed_query(self, text: str) -> list[float]:
        """단일 검색어를 검색용 벡터로 변환한다."""
        response = httpx.post(
            f"{self.base_url}/embed/query",
            json={"text": text},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["embeddings"][0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """여러 검색어를 서버 허용 크기로 나눠 벡터화한다."""
        if len(texts) == 1:
            return [self.embed_query(texts[0])]
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), MAX_QUERY_BATCH_SIZE):
            response = httpx.post(
                f"{self.base_url}/embed/queries",
                json={"texts": texts[start : start + MAX_QUERY_BATCH_SIZE]},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            embeddings.extend(payload["embeddings"])
        return embeddings
