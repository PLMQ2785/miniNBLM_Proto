from dataclasses import dataclass
from statistics import fmean


SourceKey = tuple[str, int]


@dataclass(frozen=True)
class RankedReference:
    document: str
    page_start: int | None
    page_end: int | None

    def sources(self) -> set[SourceKey]:
        if self.page_start is None:
            return set()
        page_end = self.page_end if self.page_end is not None else self.page_start
        if page_end < self.page_start:
            return set()
        return {
            (self.document, page)
            for page in range(self.page_start, page_end + 1)
        }


@dataclass(frozen=True)
class RetrievalScore:
    recall_at_k: float
    hit_at_k: float
    reciprocal_rank: float
    first_relevant_rank: int | None


def score_retrieval(
    ranked_references: list[RankedReference],
    relevant_sources: set[SourceKey],
    top_k: int,
) -> RetrievalScore:
    if not relevant_sources:
        raise ValueError("At least one relevant source is required")
    if top_k < 1:
        raise ValueError("top_k must be positive")

    retrieved_sources: set[SourceKey] = set()
    first_relevant_rank = None
    for rank, reference in enumerate(ranked_references[:top_k], start=1):
        reference_sources = reference.sources()
        retrieved_sources.update(reference_sources)
        if first_relevant_rank is None and reference_sources & relevant_sources:
            first_relevant_rank = rank

    matched_sources = retrieved_sources & relevant_sources
    recall = len(matched_sources) / len(relevant_sources)
    return RetrievalScore(
        recall_at_k=recall,
        hit_at_k=float(bool(matched_sources)),
        reciprocal_rank=(1.0 / first_relevant_rank if first_relevant_rank else 0.0),
        first_relevant_rank=first_relevant_rank,
    )


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("At least one value is required")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")

    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def aggregate_scores(
    scores: list[RetrievalScore],
    latency_ms: list[float],
) -> dict[str, float | int]:
    if not scores:
        raise ValueError("At least one retrieval score is required")
    if not latency_ms:
        raise ValueError("At least one latency sample is required")
    return {
        "recall_at_k": fmean(score.recall_at_k for score in scores),
        "hit_rate_at_k": fmean(score.hit_at_k for score in scores),
        "mrr_at_k": fmean(score.reciprocal_rank for score in scores),
        "latency_mean_ms": fmean(latency_ms),
        "latency_p50_ms": percentile(latency_ms, 0.50),
        "latency_p95_ms": percentile(latency_ms, 0.95),
        "latency_samples": len(latency_ms),
    }
