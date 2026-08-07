from app.schemas.chat import SourceRef
from app.services.retrieval_trace import RetrievalTrace
from app.services.retriever import RetrievedChunk


def test_retrieval_trace_serializes_candidates_coverage_and_outcome() -> None:
    chunk = RetrievedChunk(
        chunk_id=10,
        document_id=20,
        document_title="lesson.pdf",
        content="근거",
        page_start=3,
        page_end=3,
        score=0.91,
        source_refs={"page": 3},
    )
    trace = RetrievalTrace(request_id="request-123")
    trace.set_query_plan("독립 질문", ("독립 질문", "세부 질문"))
    trace.record_candidates(
        stage="initial.search",
        query="세부 질문",
        algorithm="dense",
        rows=[chunk],
    )
    trace.record_coverage(
        attempt=0,
        status="insufficient",
        missing_queries=("세부 질문",),
        retry_queries=("구체 검색어",),
    )

    payload = trace.complete(
        answer="근거 답변 [Source 1, Page 3]",
        chunks=[chunk],
        sources=[
            SourceRef(
                document_id=20,
                document_title="lesson.pdf",
                page=3,
                chunk_id=10,
            )
        ],
    )

    assert payload["request_id"] == "request-123"
    assert payload["query_plan"]["queries"] == ["독립 질문", "세부 질문"]
    assert payload["retrieval_events"][0]["candidates"][0]["page_start"] == 3
    assert payload["coverage_events"][0]["retry_queries"] == ["구체 검색어"]
    assert payload["outcome"]["status"] == "grounded"
    assert payload["outcome"]["cited_chunk_ids"] == [10]
