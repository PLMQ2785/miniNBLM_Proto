from dataclasses import dataclass

from app.services.retriever import _reciprocal_rank_fusion


@dataclass(frozen=True)
class StubChunk:
    id: int


def test_reciprocal_rank_fusion_combines_and_deduplicates_results() -> None:
    first = StubChunk(1)
    second = StubChunk(2)
    third = StubChunk(3)

    rows = _reciprocal_rank_fusion(
        (
            [(first, 0.1), (second, 0.2)],
            [(second, 0.9), (third, 0.8)],
            [(second, 0.7), (first, 0.6)],
        ),
        top_k=2,
    )

    assert [chunk.id for chunk, _ in rows] == [2, 1]
    assert rows[0][1] > rows[1][1]


def test_reciprocal_rank_fusion_handles_empty_sources() -> None:
    assert _reciprocal_rank_fusion(([], []), top_k=3) == []
