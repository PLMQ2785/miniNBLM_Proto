from types import SimpleNamespace

import pytest

pytest.importorskip("sentence_transformers")

from embedding_service import main


def test_rerank_endpoint_scores_pairs_in_order(monkeypatch) -> None:
    captured: dict = {}

    class _Reranker:
        def predict(self, pairs, **kwargs):
            captured["pairs"] = pairs
            captured["kwargs"] = kwargs
            return [0.25, 0.75]

    monkeypatch.setattr(main, "get_reranker", lambda: _Reranker())
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(reranker_batch_size=8),
    )
    request = main.RerankRequest(
        pairs=[
            main.RerankPair(query="question", passage="first"),
            main.RerankPair(query="question", passage="second"),
        ]
    )

    response = main.rerank(request)

    assert response.scores == [0.25, 0.75]
    assert captured["pairs"] == [
        ("question", "first"),
        ("question", "second"),
    ]
    assert captured["kwargs"] == {
        "batch_size": 8,
        "show_progress_bar": False,
        "convert_to_numpy": True,
    }


def test_rerank_request_rejects_more_than_service_limit() -> None:
    with pytest.raises(ValueError):
        main.RerankRequest(
            pairs=[
                main.RerankPair(query="question", passage=f"passage-{index}")
                for index in range(257)
            ]
        )
