import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from prometheus_client import Counter, Histogram


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter(
    "mininblm_http_requests_total",
    "HTTP requests completed by the API.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "mininblm_http_request_duration_seconds",
    "End-to-end HTTP request duration, including streamed response bodies.",
    ("method", "route"),
)
RETRIEVAL_REQUESTS = Counter(
    "mininblm_retrieval_requests_total",
    "Retrieval operations by algorithm and result status.",
    ("algorithm", "status"),
)
RETRIEVAL_DURATION = Histogram(
    "mininblm_retrieval_duration_seconds",
    "Retrieval operation duration by algorithm.",
    ("algorithm",),
)
RERANK_REQUESTS = Counter(
    "mininblm_rerank_requests_total",
    "Semantic reranking operations by result status.",
    ("status",),
)
RERANK_DURATION = Histogram(
    "mininblm_rerank_duration_seconds",
    "Semantic reranking operation duration.",
)
EVIDENCE_COVERAGE_REQUESTS = Counter(
    "mininblm_evidence_coverage_requests_total",
    "Evidence coverage checks by result status.",
    ("status",),
)
EVIDENCE_COVERAGE_DURATION = Histogram(
    "mininblm_evidence_coverage_duration_seconds",
    "Evidence coverage check duration.",
)
RETRIEVAL_RETRIES = Counter(
    "mininblm_retrieval_retries_total",
    "Targeted retrieval retries by result status.",
    ("status",),
)
CITATION_VALIDATION_REQUESTS = Counter(
    "mininblm_citation_validation_requests_total",
    "Citation validation operations by result status.",
    ("status",),
)
CITATION_VALIDATION_DURATION = Histogram(
    "mininblm_citation_validation_duration_seconds",
    "Citation validation operation duration.",
)
LLM_REQUESTS = Counter(
    "mininblm_llm_requests_total",
    "LLM operations by purpose, mode, and result status.",
    ("operation", "mode", "status"),
)
LLM_DURATION = Histogram(
    "mininblm_llm_duration_seconds",
    "LLM operation duration by purpose and mode.",
    ("operation", "mode"),
)
LLM_TIME_TO_FIRST_TOKEN = Histogram(
    "mininblm_llm_time_to_first_token_seconds",
    "Time to first non-empty token for streaming LLM operations.",
    ("operation",),
)
CHAT_STREAMS = Counter(
    "mininblm_chat_streams_total",
    "Chat streams by completion status.",
    ("status",),
)


class JsonLogFormatter(logging.Formatter):
    """요청 로그를 수집기가 읽는 JSON 한 줄 형식으로 만든다."""
    def format(self, record: logging.LogRecord) -> str:
        """로그 레코드와 요청 문맥을 구조화된 JSON으로 직렬화한다."""
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for field in ("method", "route", "status", "duration_ms", "operation", "algorithm"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        retrieval_trace = getattr(record, "retrieval_trace", None)
        if retrieval_trace is not None:
            payload["retrieval_trace"] = retrieval_trace
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """애플리케이션과 Uvicorn 로그를 단일 JSON 출력으로 통합한다."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for logger_name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _request_id(headers: list[tuple[bytes, bytes]]) -> str:
    """안전한 요청 식별자를 헤더에서 읽거나 새로 발급한다."""
    for name, value in headers:
        if name.lower() != b"x-request-id":
            continue
        candidate = value.decode("latin-1").strip()
        if candidate and len(candidate) <= 128 and all(
            character.isalnum() or character in "._-" for character in candidate
        ):
            return candidate
    return uuid.uuid4().hex


class RequestObservabilityMiddleware:
    """HTTP 요청에 식별자·구조화 로그·Prometheus 측정을 더한다."""
    def __init__(self, app) -> None:
        """하위 ASGI 앱과 HTTP 전용 로거를 보관한다."""
        self.app = app
        self.logger = logging.getLogger("mininblm.http")

    async def __call__(self, scope, receive, send) -> None:
        """HTTP 요청의 식별자와 지표 수명 주기를 감싼다."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope.get("headers", []))
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        # 예외 요청도 로그와 지표에서 500으로 집계한다.
        status_code = 500

        async def send_with_request_id(message) -> None:
            """응답에 요청 식별자를 싣고 최종 상태 코드를 기록한다."""
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            self.logger.exception("Unhandled HTTP request error")
            raise
        finally:
            duration = time.perf_counter() - started_at
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            method = scope.get("method", "UNKNOWN")
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration)
            self.logger.info(
                "HTTP request completed",
                extra={
                    "method": method,
                    "route": route,
                    "status": status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            request_id_context.reset(token)
