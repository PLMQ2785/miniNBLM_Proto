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
    def format(self, record: logging.LogRecord) -> str:
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
    def __init__(self, app) -> None:
        self.app = app
        self.logger = logging.getLogger("mininblm.http")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope.get("headers", []))
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        # Exceptions keep the default 500 status for metrics and logs.
        status_code = 500

        async def send_with_request_id(message) -> None:
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
