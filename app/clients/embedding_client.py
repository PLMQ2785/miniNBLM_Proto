import httpx

from app.config import settings


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
