from dataclasses import dataclass

from app.services import reranker


@dataclass
class _Chunk:
    """재정렬 입력으로 쓰는 최소 청크 대역이다."""

    id: int
    content: str
    embedding: list[float]


def _embedding_rows():
    """임베딩 재정렬 검증에 쓸 고정 후보를 만든다."""
    return [
        (_Chunk(1, "reset passage", [1.0, 0.0]), 0.9, "reset.pdf"),
        (_Chunk(2, "revert passage", [0.0, 1.0]), 0.8, "revert.pdf"),
        (_Chunk(3, "overall passage", [0.7, 0.7]), 0.7, "overall.pdf"),
    ]


def _cross_rows():
    """교차 인코더의 query-passage 순서를 검증할 후보를 만든다."""
    return [
        (_Chunk(1, "facet passage", [1.0, 0.0]), 0.9, "doc"),
        (_Chunk(2, "original passage", [0.0, 1.0]), 0.8, "doc"),
        (_Chunk(3, "unrelated passage", [0.5, 0.5]), 0.7, "doc"),
    ]


def test_embedding_reranker_uses_bge_query_embeddings(monkeypatch) -> None:
    """BGE 질의 임베딩으로 가장 가까운 후보를 선택하는지 보장한다."""

    class _EmbeddingClient:
        """질의 임베딩 결과를 고정하는 클라이언트 대역이다."""

        def embed_queries(self, texts):
            """입력 질의를 확인하고 대응 임베딩을 반환한다."""
            assert texts == ["reset question"]
            return [[1.0, 0.0]]

    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("reset question", _embedding_rows(), top_k=1)

    assert selected[0][0].id == 1


def test_embedding_reranker_preserves_best_candidate_for_each_goal(monkeypatch) -> None:
    """상위 제한 안에서 각 목표의 최적 후보를 모두 보존하는지 보장한다."""

    class _EmbeddingClient:
        """전체 질문과 목표별 질의 임베딩을 제공하는 대역이다."""

        def embed_queries(self, texts):
            """질의 순서를 확인하고 목표별 임베딩을 반환한다."""
            assert texts == ["overall question", "reset query", "revert query"]
            return [[0.7, 0.7], [1.0, 0.0], [0.0, 1.0]]

    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows(
        "overall question",
        _embedding_rows(),
        top_k=2,
        queries=["reset query", "revert query"],
        goal_query_groups=(
            ("reset", ("reset query",)),
            ("revert", ("revert query",)),
        ),
    )

    assert {row[0].id for row in selected} == {1, 2}


def test_embedding_failure_preserves_retrieval_rank(monkeypatch) -> None:
    """임베딩 실패 시 검색 순위를 그대로 유지하는지 보장한다."""

    class _FailedClient:
        """임베딩 장애를 발생시키는 클라이언트 대역이다."""

        def embed_queries(self, texts):
            """재정렬의 장애 대체 경로를 위해 오류를 낸다."""
            raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(reranker, "EmbeddingClient", _FailedClient)

    selected = reranker.rerank_rows("question", _embedding_rows(), top_k=2)

    assert [row[0].id for row in selected] == [1, 2]


def test_cross_encoder_reranker_preserves_facet_anchor(monkeypatch) -> None:
    """교차 인코더가 세부 질의 후보를 최종 결과에 보존하는지 검증한다."""
    captured_pairs: list[tuple[str, str]] = []

    class _Client:
        """query-passage 점수와 호출 순서를 고정하는 대역이다."""

        def score_pairs(self, pairs):
            """입력 순서를 기록하고 미리 정한 관련도 점수를 반환한다."""
            captured_pairs.extend(pairs)
            return [0.1, 0.9, 0.2, 0.95, 0.1, 0.2]

    monkeypatch.setattr(reranker.settings, "reranker_mode", "cross_encoder")
    monkeypatch.setattr(reranker, "RerankerClient", _Client)

    selected = reranker.rerank_rows(
        "original question",
        _cross_rows(),
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
    """교차 인코더 장애 시 임베딩 재정렬로 내려가는지 검증한다."""

    class _FailedClient:
        """교차 인코더 서비스 장애를 재현한다."""

        def score_pairs(self, pairs):
            """대체 경로를 확인하도록 오류를 낸다."""
            raise RuntimeError("reranker unavailable")

    class _EmbeddingClient:
        """대체 경로에서 사용할 질의 임베딩을 고정한다."""

        def embed_queries(self, texts):
            """두 번째 후보와 가까운 임베딩을 반환한다."""
            return [[0.0, 1.0] for _ in texts]

    monkeypatch.setattr(reranker.settings, "reranker_mode", "cross_encoder")
    monkeypatch.setattr(reranker, "RerankerClient", _FailedClient)
    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("question", _cross_rows(), top_k=1)

    assert selected[0][0].id == 2


def test_embedding_mode_does_not_call_cross_encoder(monkeypatch) -> None:
    """임베딩 모드가 교차 인코더 클라이언트를 만들지 않는지 검증한다."""

    class _UnexpectedClient:
        """생성되면 즉시 실패해 잘못된 경로 진입을 알린다."""

        def __init__(self):
            """교차 인코더 생성 자체를 실패로 처리한다."""
            raise AssertionError("cross-encoder must not be created")

    class _EmbeddingClient:
        """첫 후보와 가까운 임베딩을 반환한다."""

        def embed_queries(self, texts):
            """임베딩 모드의 고정 질의 벡터를 반환한다."""
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(reranker.settings, "reranker_mode", "embedding")
    monkeypatch.setattr(reranker, "RerankerClient", _UnexpectedClient)
    monkeypatch.setattr(reranker, "EmbeddingClient", _EmbeddingClient)

    selected = reranker.rerank_rows("question", _cross_rows(), top_k=1)

    assert selected[0][0].id == 1
