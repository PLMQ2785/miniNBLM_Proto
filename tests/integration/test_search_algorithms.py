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
            owner_id=user.id,
            question="낙상 발생 대응 순서",
            top_k=2,
        )

        assert results
        assert results[0].chunk_id == target_id
        assert results[0].document_title == document.title
        assert results[0].page_start == 3


def test_keyword_search_matches_partial_terms_in_a_natural_language_question(
    db: Session,
    user_factory,
    document_factory,
) -> None:
    user = user_factory("keyword-natural-language")
    document = document_factory(user)
    target = Chunk(
        document_id=document.id,
        page_start=5,
        page_end=5,
        chunk_index=0,
        content="낙상 예방을 위해 침상 바퀴를 고정하고 호출벨을 가까이 둔다.",
        embedding=[1.0] + [0.0] * 1023,
    )
    db.add(target)
    db.commit()
    target_id = target.id

    configuration = retrieval_config_repository.get_configuration(db)
    configuration.active_search_algorithm_key = "keyword"
    db.commit()

    results = retrieve_chunks(
        db,
        owner_id=user.id,
        question="낙상 예방 환경 관리 방법은 무엇인가요?",
        top_k=5,
    )

    assert [result.chunk_id for result in results] == [target_id]


def test_all_search_algorithms_are_scoped_to_the_owners_indexed_documents(
    db: Session,
    user_factory,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory("scope-user")
    other_user = user_factory("other-user")
    first_document = document_factory(user, title="first.pdf")
    second_document = document_factory(user, title="second.pdf")
    processing_document = document_factory(user, title="processing.pdf", status="processing")
    foreign_document = document_factory(other_user, title="foreign.pdf")
    embedding = [1.0] + [0.0] * 1023
    db.add_all(
        [
            Chunk(
                document_id=first_document.id,
                page_start=1,
                page_end=1,
                chunk_index=0,
                content="첫 번째 문서의 안전 수칙",
                embedding=embedding,
            ),
            Chunk(
                document_id=second_document.id,
                page_start=1,
                page_end=1,
                chunk_index=0,
                content="두 번째 문서의 안전 수칙",
                embedding=embedding,
            ),
            Chunk(
                document_id=processing_document.id,
                page_start=1,
                page_end=1,
                chunk_index=0,
                content="처리 중인 문서의 안전 수칙",
                embedding=embedding,
            ),
            Chunk(
                document_id=foreign_document.id,
                page_start=1,
                page_end=1,
                chunk_index=0,
                content="다른 사용자 문서의 안전 수칙",
                embedding=embedding,
            ),
        ]
    )
    db.commit()
    monkeypatch.setattr(EmbeddingClient, "embed_query", lambda self, question: embedding)

    configuration = retrieval_config_repository.get_configuration(db)
    for algorithm_key in ("dense", "keyword", "substring", "hybrid"):
        configuration.active_search_algorithm_key = algorithm_key
        db.commit()

        results = retrieve_chunks(
            db,
            owner_id=user.id,
            question="안전 수칙",
            top_k=10,
        )

        assert {result.document_id for result in results} == {
            first_document.id,
            second_document.id,
        }
        assert {result.document_title for result in results} == {
            first_document.title,
            second_document.title,
        }
