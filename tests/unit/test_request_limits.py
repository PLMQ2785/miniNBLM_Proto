from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.request_limits import RequestBodyLimitMiddleware


def _client(max_body_bytes: int) -> TestClient:
    """요청 본문 제한을 적용한 최소 HTTP 앱을 만든다."""
    app = FastAPI()
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=max_body_bytes,
    )

    @app.post("/body")
    async def body_size(request: Request) -> dict[str, int]:
        """미들웨어를 통과한 요청 본문의 실제 크기를 돌려준다."""
        return {"size": len(await request.body())}

    return TestClient(app)


def test_request_at_limit_is_accepted() -> None:
    """제한과 같은 크기의 요청 본문은 정상 처리한다."""
    response = _client(5).post("/body", content=b"12345")

    assert response.status_code == 200
    assert response.json() == {"size": 5}


def test_content_length_over_limit_is_rejected() -> None:
    """Content-Length가 제한을 넘는 요청은 413으로 거부한다."""
    response = _client(5).post("/body", content=b"123456")

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the 5 byte limit"}


def test_chunked_body_over_limit_is_rejected_while_streaming() -> None:
    """분할 전송 본문은 읽는 도중 누적 크기가 제한을 넘으면 거부한다."""
    response = _client(5).post("/body", content=iter((b"123", b"456")))

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the 5 byte limit"}
