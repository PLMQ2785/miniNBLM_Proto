from starlette.responses import JSONResponse


class RequestBodyTooLargeError(Exception):
    """스트리밍 중 요청 본문이 허용 크기를 넘었음을 알린다."""
    pass


class RequestBodyLimitMiddleware:
    """파싱 전에 요청 본문 크기를 제한하는 ASGI 미들웨어다."""
    def __init__(self, app, *, max_body_bytes: int) -> None:
        """하위 앱과 허용할 최대 본문 바이트를 보관한다."""
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send) -> None:
        """헤더와 실제 스트림 크기를 모두 검사해 초과 요청을 거절한다."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 멀티파트 파싱 전에 크기가 확실한 초과 요청을 거절한다.
        content_length = _content_length(scope.get("headers", []))
        if content_length is not None and content_length > self.max_body_bytes:
            await self._reject(scope, receive, send)
            return

        received_bytes = 0
        response_started = False
        # Content-Length가 없을 수 있어 스트림 도착분도 누적한다.
        async def receive_with_limit():
            """수신 청크를 누적해 제한 초과 시 파싱을 중단한다."""
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise RequestBodyTooLargeError
            return message

        async def track_response(message) -> None:
            """응답 시작 여부를 기록해 이중 응답을 피한다."""
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive_with_limit, track_response)
        except RequestBodyTooLargeError:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope, receive, send) -> None:
        """본문을 소비하지 않고 413 JSON 응답을 보낸다."""
        response = JSONResponse(
            status_code=413,
            content={
                "detail": (
                    "Request body exceeds the "
                    f"{self.max_body_bytes} byte limit"
                )
            },
        )
        await response(scope, receive, send)


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    """유효한 Content-Length 값만 헤더에서 읽는다."""
    for name, value in headers:
        if name.lower() != b"content-length":
            continue
        try:
            content_length = int(value)
        except ValueError:
            return None
        return content_length if content_length >= 0 else None
    return None
