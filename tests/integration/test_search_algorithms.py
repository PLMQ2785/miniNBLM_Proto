from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.clients.embedding_client import EmbeddingClient
from app.models.chunk import Chunk
from app.models.page import DocumentPage
from app.repositories import retrieval_config_repository
from app.services import hierarchical_retriever
from app.services.hierarchical_retriever import retrieve_hierarchical_chunks
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


def test_multi_query_search_combines_evidence_for_different_facets(
    db: Session,
    user_factory,
    document_factory,
) -> None:
    user = user_factory("multi-query-searcher")
    document = document_factory(user, title="git-collaboration.pdf")
    reset_chunk = Chunk(
        document_id=document.id,
        page_start=10,
        page_end=10,
        chunk_index=0,
        content="git reset은 브랜치의 커밋 이력을 과거 시점으로 이동시킨다.",
        embedding=[1.0] + [0.0] * 1023,
    )
    revert_chunk = Chunk(
        document_id=document.id,
        page_start=11,
        page_end=11,
        chunk_index=1,
        content="git revert는 기존 커밋을 취소하는 새로운 커밋을 생성한다.",
        embedding=[0.0, 1.0] + [0.0] * 1022,
    )
    db.add_all([reset_chunk, revert_chunk])
    db.commit()
    reset_chunk_id = reset_chunk.id
    revert_chunk_id = revert_chunk.id

    configuration = retrieval_config_repository.get_configuration(db)
    configuration.active_search_algorithm_key = "keyword"
    db.commit()

    results = retrieve_chunks(
        db,
        owner_id=user.id,
        question="push된 커밋에서 reset 대신 revert를 사용하는 이유",
        queries=("git reset 커밋 이력 이동", "git revert 새로운 취소 커밋 생성"),
        top_k=2,
    )

    assert {result.chunk_id for result in results} == {reset_chunk_id, revert_chunk_id}


def test_retrieval_appends_adjacent_chunks_without_changing_the_seed_rank(
    db: Session,
    user_factory,
    document_factory,
) -> None:
    user = user_factory("adjacent-context-searcher")
    document = document_factory(user, title="git-history.pdf")
    previous = Chunk(
        document_id=document.id,
        page_start=20,
        page_end=20,
        chunk_index=0,
        content="공유 저장소에서는 다른 개발자가 기존 커밋 이력을 기반으로 작업한다.",
        embedding=[0.0, 1.0] + [0.0] * 1022,
    )
    anchor = Chunk(
        document_id=document.id,
        page_start=21,
        page_end=21,
        chunk_index=1,
        content="git revert는 기존 변경을 취소하는 새로운 커밋을 생성한다.",
        embedding=[1.0] + [0.0] * 1023,
    )
    following = Chunk(
        document_id=document.id,
        page_start=22,
        page_end=22,
        chunk_index=2,
        content="기존 이력을 보존하면 원격 저장소의 협업자에게 영향을 줄이지 않는다.",
        embedding=[0.0, 1.0] + [0.0] * 1022,
    )
    unrelated = Chunk(
        document_id=document.id,
        page_start=30,
        page_end=30,
        chunk_index=9,
        content="브랜치 이름을 변경하는 방법",
        embedding=[0.0, 1.0] + [0.0] * 1022,
    )
    db.add_all([previous, anchor, following, unrelated])
    db.commit()
    anchor_id = anchor.id
    previous_id = previous.id
    following_id = following.id

    configuration = retrieval_config_repository.get_configuration(db)
    configuration.active_search_algorithm_key = "keyword"
    db.commit()

    results = retrieve_chunks(
        db,
        owner_id=user.id,
        question="git revert 새로운 커밋 생성",
        top_k=1,
    )

    assert [result.chunk_id for result in results] == [anchor_id, previous_id, following_id]
    assert [result.page_start for result in results] == [21, 20, 22]


def test_adjacent_expansion_excludes_deleted_chunks(
    db: Session,
    user_factory,
    document_factory,
) -> None:
    user = user_factory("deleted-adjacent-searcher")
    document = document_factory(user, title="deleted-neighbor.pdf")
    anchor = Chunk(
        document_id=document.id,
        page_start=1,
        page_end=1,
        chunk_index=0,
        content="고유한 검색 기준 문구",
        embedding=[1.0] + [0.0] * 1023,
    )
    deleted_neighbor = Chunk(
        document_id=document.id,
        page_start=2,
        page_end=2,
        chunk_index=1,
        content="삭제된 인접 문맥",
        embedding=[0.0, 1.0] + [0.0] * 1022,
        deleted_at=datetime.now(UTC),
    )
    db.add_all([anchor, deleted_neighbor])
    db.commit()
    anchor_id = anchor.id

    configuration = retrieval_config_repository.get_configuration(db)
    configuration.active_search_algorithm_key = "keyword"
    db.commit()

    results = retrieve_chunks(
        db,
        owner_id=user.id,
        question="고유한 검색 기준 문구",
        top_k=1,
    )

    assert [result.chunk_id for result in results] == [anchor_id]


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


def test_hierarchical_fallback_searches_pages_then_scopes_chunks_to_owner(
    db: Session,
    user_factory,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory("hierarchical-owner")
    other_user = user_factory("hierarchical-other")
    document = document_factory(user, title="git-pages.pdf")
    foreign_document = document_factory(other_user, title="foreign-pages.pdf")
    target = Chunk(
        document_id=document.id,
        page_start=5,
        page_end=5,
        chunk_index=0,
        content="공유 원격 이력을 재작성하면 협업자의 로컬 이력이 분기된다.",
        embedding=[1.0] + [0.0] * 1023,
    )
    foreign = Chunk(
        document_id=foreign_document.id,
        page_start=5,
        page_end=5,
        chunk_index=0,
        content="공유 원격 이력을 재작성하면 협업자의 로컬 이력이 분기된다.",
        embedding=[1.0] + [0.0] * 1023,
    )
    db.add_all(
        [
            DocumentPage(
                document_id=document.id,
                page_number=5,
                text="DVCS에서 공유 원격 이력 재작성은 협업자의 로컬 이력을 분기시킨다.",
            ),
            DocumentPage(
                document_id=document.id,
                page_number=8,
                text="브랜치 이름을 변경하는 방법",
            ),
            DocumentPage(
                document_id=foreign_document.id,
                page_number=5,
                text="DVCS에서 공유 원격 이력 재작성은 협업자의 로컬 이력을 분기시킨다.",
            ),
            target,
            foreign,
        ]
    )
    db.commit()
    target_id = target.id
    monkeypatch.setattr(
        hierarchical_retriever,
        "rerank_rows",
        lambda question, rows, top_k, queries: rows[:top_k],
    )

    results = retrieve_hierarchical_chunks(
        db=db,
        owner_id=user.id,
        question="push 후 reset이 협업에 미치는 영향",
        queries=("공유 원격 이력 재작성 협업자 로컬 이력 분기",),
    )

    assert [result.chunk_id for result in results] == [target_id]
    assert results[0].document_title == "git-pages.pdf"
    assert results[0].page_start == 5
