from app.schemas.chat import SourceRef
from app.services.query_rewriter import EvidenceGoal
from app.services.retrieval_trace import RetrievalTrace
from app.services.retriever import RetrievedChunk


def test_retrieval_trace_serializes_goal_candidates_coverage_and_outcome() -> None:
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
    goals = (
        EvidenceGoal("g1", "세부 근거", ("세부 질문",)),
    )
    trace = RetrievalTrace(request_id="request-123")
    trace.set_query_plan("독립 질문", goals)
    trace.record_candidates(
        stage="initial.search",
        query="세부 질문",
        algorithm="dense",
        rows=[chunk],
        goal_ids=("g1",),
    )
    trace.record_coverage(
        attempt=0,
        status="supported",
        goal_results=[
            {
                "goal_id": "g1",
                "description": "세부 근거",
                "status": "supported",
                "evidence": [
                    {
                        "chunk_id": 10,
                        "document_title": "lesson.pdf",
                        "page_start": 3,
                        "page_end": 3,
                    }
                ],
                "retry_queries": [],
            }
        ],
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

    assert payload["schema_version"] == 4
    assert payload["request_id"] == "request-123"
    assert payload["query_plan"]["evidence_goals"][0]["goal_id"] == "g1"
    assert payload["retrieval_events"][0]["goal_ids"] == ["g1"]
    assert payload["retrieval_events"][0]["candidates"][0]["page_start"] == 3
    assert payload["coverage_events"][0]["goals"][0]["evidence"][0]["chunk_id"] == 10
    assert payload["outcome"]["status"] == "grounded"
    assert payload["outcome"]["cited_chunk_ids"] == [10]
    assert payload["outcome"]["final_modalities"] == ["text"]
