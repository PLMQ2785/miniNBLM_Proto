import pytest
from sqlalchemy.orm import Session

from app.clients.embedding_client import EmbeddingClient
from app.models.chunk import Chunk
from app.repositories import retrieval_config_repository
from app.services.retriever import retrieve_chunks


pytestmark = pytest.mark.integration


def test_all_search_algorithms_return_the_matching_chunk(
    db: Session,
    user_factory,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory("searcher")
    document = document_factory(user)
    target_embedding = [1.0] + [0.0] * 1023
    other_embedding = [0.0, 1.0] + [0.0] * 1022
    target = Chunk(
        document_id=document.id,
        page_start=3,
        page_end=3,
        chunk_index=0,
        content="낙상 발생 대응 순서",
        embedding=target_embedding,
        source_refs={"page": 3},
    )
    distractor = Chunk(
        document_id=document.id,
        page_start=8,
        page_end=8,
        chunk_index=1,
        content="퇴원 전 복약 안내와 다음 진료 예약",
        embedding=other_embedding,
        source_refs={"page": 8},
    )
    db.add_all([target, distractor])
    db.commit()
    target_id = target.id
    monkeypatch.setattr(
        EmbeddingClient,
        "embed_query",
        lambda self, question: target_embedding,
    )

    configuration = retrieval_config_repository.get_configuration(db)
    for algorithm_key in ("dense", "keyword", "substring", "hybrid"):
        configuration.active_search_algorithm_key = algorithm_key
        db.commit()

        results = retrieve_chunks(
            db,
            document_id=document.id,
            question="낙상 발생 대응 순서",
            top_k=2,
        )

        assert results
        assert results[0].chunk_id == target_id
        assert results[0].page_start == 3


def test_search_is_scoped_to_the_requested_document(
    db: Session,
    user_factory,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory("scope-user")
    requested_document = document_factory(user, title="requested.pdf")
    other_document = document_factory(user, title="other.pdf")
    embedding = [1.0] + [0.0] * 1023
    db.add_all(
        [
            Chunk(
                document_id=requested_document.id,
                page_start=1,
                page_end=1,
                chunk_index=0,
                content="요청한 문서의 안전 수칙",
                embedding=embedding,
            ),
            Chunk(
                document_id=other_document.id,
                page_start=1,
                page_end=1,
                chunk_index=0,
                content="다른 문서의 안전 수칙",
                embedding=embedding,
            ),
        ]
    )
    db.commit()
    monkeypatch.setattr(EmbeddingClient, "embed_query", lambda self, question: embedding)

    results = retrieve_chunks(
        db,
        document_id=requested_document.id,
        question="안전 수칙",
        top_k=5,
    )

    assert results
    assert {result.document_id for result in results} == {requested_document.id}
