import json
import os
import time
from pathlib import Path

import httpx
import psycopg
import pytest
from prometheus_client.parser import text_string_to_metric_families


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("RUN_REAL_E2E") != "1",
        reason="Run through ./scripts/e2e.sh",
    ),
]


def _wait_until_indexed(client: httpx.Client, document_id: int, timeout: float = 240.0) -> dict:
    """실제 문서가 색인 완료 또는 실패할 때까지 API 상태를 확인한다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/documents/{document_id}")
        response.raise_for_status()
        document = response.json()
        if document["status"] == "indexed":
            return document
        if document["status"] == "failed":
            pytest.fail(f"Document indexing failed: {document['error_message']}")
        time.sleep(1)
    pytest.fail(f"Document {document_id} was not indexed within {timeout:.0f}s")


def _ask(client: httpx.Client, document_id: int, question: str) -> dict:
    """선택 문서 범위의 실제 비스트리밍 답변이 비어 있지 않은지 확인한다."""
    response = client.post(
        "/chat",
        json={"document_id": document_id, "question": question},
        timeout=180.0,
    )
    response.raise_for_status()
    payload = response.json()
    assert payload["answer"].strip()
    return payload


def _ask_stream(client: httpx.Client, document_id: int, question: str) -> dict:
    """선택 문서 범위의 SSE 이벤트를 조립하고 완료·분할 전송 계약을 확인한다."""
    answer_parts: list[str] = []
    sources: list[dict] = []
    session: dict | None = None
    completed = False
    event = "message"
    delta_count = 0

    with client.stream(
        "POST",
        "/chat/stream",
        json={"document_id": document_id, "question": question},
        timeout=180.0,
    ) as response:
        response.raise_for_status()
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-request-id"]
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                payload = json.loads(line.removeprefix("data:").strip())
                if event == "session":
                    session = payload
                elif event == "delta":
                    answer_parts.append(payload["text"])
                    delta_count += 1
                elif event == "sources":
                    sources = payload
                elif event == "done":
                    session = payload["session"]
                    completed = True
                elif event == "error":
                    pytest.fail(f"Streaming chat failed: {payload}")

    assert completed
    assert session is not None
    assert delta_count >= 2
    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "session": session,
        "delta_count": delta_count,
    }


def _has_metric_sample(metrics_text: str, name: str, labels: dict[str, str]) -> bool:
    """노출된 메트릭에 이름과 라벨이 일치하는 표본이 있는지 확인한다."""
    return any(
        sample.name == name and labels.items() <= sample.labels.items()
        for family in text_string_to_metric_families(metrics_text)
        for sample in family.samples
    )


def test_real_pdf_embedding_retrieval_generation_and_grounding() -> None:
    """실제 PDF·임베딩·검색·생성·근거 제한과 정리를 끝까지 검증한다."""
    base_url = os.environ["E2E_BASE_URL"]
    pdf_path = Path(os.environ["E2E_PDF_PATH"])
    database_dsn = os.environ["E2E_DATABASE_DSN"]

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        registration = client.post(
            "/auth/register",
            json={"username": "e2e-student", "password": "e2e-password"},
        )
        assert registration.status_code == 201

        with pdf_path.open("rb") as source:
            upload = client.post(
                "/documents",
                files={"file": (pdf_path.name, source, "application/pdf")},
                timeout=60.0,
            )
        upload.raise_for_status()
        document_id = upload.json()["document_id"]

        # 실제 모델 검증이 중간에 실패해도 업로드 문서는 반드시 정리한다.
        try:
            _wait_until_indexed(client, document_id)

            with psycopg.connect(database_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM document_pages WHERE document_id = %s",
                        (document_id,),
                    )
                    assert cursor.fetchone()[0] == 4
                    cursor.execute(
                        "SELECT count(*) FROM chunks WHERE document_id = %s AND embedding IS NOT NULL",
                        (document_id,),
                    )
                    assert cursor.fetchone()[0] >= 4

            grounded = _ask_stream(
                client,
                document_id,
                "이 자료에서 고위험군을 나타내는 가상의 표식은 무엇인가?",
            )
            assert "청록색" in grounded["answer"]
            assert "삼각" in grounded["answer"]
            assert any(source["page"] == 1 for source in grounded["sources"])
            assert all(source["document_title"] == pdf_path.name for source in grounded["sources"])

            outside = _ask(
                client,
                document_id,
                "이 자료에 없는 2035년 서울의 평균 강수량을 알려줘.",
            )
            assert any(
                marker in outside["answer"]
                for marker in ("확인되지 않습니다", "업로드된 자료만으로는")
            )
            assert outside["sources"] == []

            metrics = client.get("/metrics")
            metrics.raise_for_status()
            assert _has_metric_sample(
                metrics.text,
                "mininblm_chat_streams_total",
                {"status": "success"},
            )
            assert _has_metric_sample(
                metrics.text,
                "mininblm_llm_requests_total",
                {"operation": "answer", "mode": "stream", "status": "success"},
            )
            assert _has_metric_sample(
                metrics.text,
                "mininblm_retrieval_requests_total",
                {"algorithm": "dense", "status": "success"},
            )
            assert _has_metric_sample(
                metrics.text,
                "mininblm_rerank_requests_total",
                {"status": "success"},
            )
        finally:
            delete = client.delete(f"/documents/{document_id}")
            assert delete.status_code == 204
