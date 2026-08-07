import httpx

from app.config import settings


MAX_QUERY_BATCH_SIZE = 5


class EmbeddingClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or settings.embedding_base_url).rstrip("/")
        self.timeout = timeout

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embed/documents",
            json={"texts": texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["embeddings"]

    def embed_query(self, text: str) -> list[float]:
        response = httpx.post(
            f"{self.base_url}/embed/query",
            json={"text": text},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["embeddings"][0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
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
