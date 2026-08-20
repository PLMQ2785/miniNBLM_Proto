from starlette.responses import JSONResponse


class RequestBodyTooLargeError(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Reject known oversized bodies before Starlette starts parsing multipart data.
        content_length = _content_length(scope.get("headers", []))
        if content_length is not None and content_length > self.max_body_bytes:
            await self._reject(scope, receive, send)
            return

        received_bytes = 0
        response_started = False
        # Content-Length is optional, so streamed bodies are counted as they arrive.
        async def receive_with_limit():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise RequestBodyTooLargeError
            return message

        async def track_response(message) -> None:
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
    for name, value in headers:
        if name.lower() != b"content-length":
            continue
        try:
            content_length = int(value)
        except ValueError:
            return None
        return content_length if content_length >= 0 else None
    return None
