import httpx

from app.config import settings


MAX_RERANK_BATCH_SIZE = 256


class RerankerClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (
            base_url or settings.reranker_base_url or settings.embedding_base_url
        ).rstrip("/")
        self.timeout = timeout

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(pairs), MAX_RERANK_BATCH_SIZE):
            batch = pairs[start : start + MAX_RERANK_BATCH_SIZE]
            response = httpx.post(
                f"{self.base_url}/rerank",
                json={
                    "pairs": [
                        {"query": query, "passage": passage}
                        for query, passage in batch
                    ]
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            batch_scores = response.json().get("scores")
            if not isinstance(batch_scores, list) or len(batch_scores) != len(batch):
                raise ValueError("Reranker returned an invalid score count")
            scores.extend(float(score) for score in batch_scores)
        return scores
