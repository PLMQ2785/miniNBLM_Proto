from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.request_limits import RequestBodyLimitMiddleware


def _client(max_body_bytes: int) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=max_body_bytes,
    )

    @app.post("/body")
    async def body_size(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    return TestClient(app)


def test_request_at_limit_is_accepted() -> None:
    response = _client(5).post("/body", content=b"12345")

    assert response.status_code == 200
    assert response.json() == {"size": 5}


def test_content_length_over_limit_is_rejected() -> None:
    response = _client(5).post("/body", content=b"123456")

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the 5 byte limit"}


def test_chunked_body_over_limit_is_rejected_while_streaming() -> None:
    response = _client(5).post("/body", content=iter((b"123", b"456")))

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the 5 byte limit"}
