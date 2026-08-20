import json
import logging

from app.observability import JsonLogFormatter, _request_id, request_id_context


def test_json_log_formatter_includes_request_context() -> None:
    """JSON 로그에는 요청 식별자와 HTTP 문맥이 함께 기록된다."""
    token = request_id_context.set("request-123")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="completed",
            args=(),
            exc_info=None,
        )
        record.method = "GET"
        record.route = "/health"
        record.status = 200

        payload = json.loads(JsonLogFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert payload["request_id"] == "request-123"
    assert payload["method"] == "GET"
    assert payload["route"] == "/health"
    assert payload["status"] == 200


def test_request_id_accepts_safe_header_and_replaces_invalid_value() -> None:
    """안전한 요청 식별자는 유지하고 잘못된 값은 새 값으로 대체한다."""
    assert _request_id([(b"x-request-id", b"client-request_1")]) == "client-request_1"
    generated = _request_id([(b"x-request-id", b"invalid request id")])

    assert len(generated) == 32
    assert generated.isalnum()
