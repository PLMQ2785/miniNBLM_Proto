import logging
import re
import time
from collections.abc import Iterator

from openai import OpenAI

from app.config import LLMEndpoint
from app.observability import (
    LLM_CONTEXT_RECOVERIES,
    LLM_DURATION,
    LLM_REQUESTS,
    LLM_TIME_TO_FIRST_TOKEN,
)
from app.services.language_model_service import get_active_endpoint


logger = logging.getLogger(__name__)

MAX_TOKENS_BY_OPERATION = {
    "query_rewrite": 512,
    "query_rewrite_repair": 512,
    "evidence_coverage": 256,
    "citation_validation": 1400,
    "answer": 900,
    "answer_retry": 900,
    "vision_caption": 900,
}
DEFAULT_MAX_TOKENS = 1024
CONTEXT_LENGTH_ERROR_PATTERN = re.compile(
    r"maximum context length is (?P<limit>[\d,]+) tokens.*?"
    r"requested (?P<requested>[\d,]+) output tokens.*?"
    r"(?:at least )?(?P<input>[\d,]+) input tokens",
    re.IGNORECASE | re.DOTALL,
)
INPUT_FIRST_CONTEXT_ERROR_PATTERN = re.compile(
    r"(?:input|prompt)(?: length| contains)?(?: of)? (?P<input>[\d,]+) tokens.*?"
    r"(?:maximum context length|context length|max_seq_len)(?: is| of)? "
    r"(?P<limit>[\d,]+)",
    re.IGNORECASE | re.DOTALL,
)
CONTEXT_ERROR_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "context length exceeded",
    "max_seq_len",
    "too many tokens",
)
CONTEXT_RETRY_TOKEN_MARGIN = 16
MIN_CONTEXT_RETRY_OUTPUT_TOKENS = 128


class ContextLengthExceededError(RuntimeError):
    """모델 입력 한도를 넘긴 호출과 서버가 알려준 토큰 수를 전달한다."""

    def __init__(
        self,
        message: str,
        *,
        context_limit: int | None = None,
        input_tokens: int | None = None,
    ) -> None:
        """원본 오류 문구와 선택적 한도 정보를 보존한다."""
        super().__init__(message)
        self.context_limit = context_limit
        self.input_tokens = input_tokens


def _context_length_error(exc: Exception) -> ContextLengthExceededError | None:
    """OpenAI 호환 서버별 오류 형태를 공통 컨텍스트 초과 오류로 바꾼다."""
    if isinstance(exc, ContextLengthExceededError):
        return exc
    body = getattr(exc, "body", None)
    error_text = f"{exc}\n{body if body is not None else ''}"
    normalized = error_text.casefold()
    if not any(marker in normalized for marker in CONTEXT_ERROR_MARKERS):
        return None

    match = CONTEXT_LENGTH_ERROR_PATTERN.search(error_text)
    if match is None:
        match = INPUT_FIRST_CONTEXT_ERROR_PATTERN.search(error_text)
    context_limit = (
        int(match.group("limit").replace(",", ""))
        if match is not None
        else None
    )
    input_tokens = (
        int(match.group("input").replace(",", ""))
        if match is not None
        else None
    )
    return ContextLengthExceededError(
        str(exc),
        context_limit=context_limit,
        input_tokens=input_tokens,
    )


def _reduced_output_token_budget(exc: Exception, current_max_tokens: int) -> int | None:
    """컨텍스트 초과 응답에서 한 번 재시도할 출력 예산을 계산한다."""
    context_error = _context_length_error(exc)
    if (
        context_error is None
        or context_error.context_limit is None
        or context_error.input_tokens is None
    ):
        return None
    # 호환 엔드포인트의 토크나이저 오차를 흡수할 여유를 둔다.
    available_output_tokens = (
        context_error.context_limit
        - context_error.input_tokens
        - CONTEXT_RETRY_TOKEN_MARGIN
    )
    if (
        available_output_tokens < MIN_CONTEXT_RETRY_OUTPUT_TOKENS
        or available_output_tokens >= current_max_tokens
    ):
        return None
    return available_output_tokens


class LLMClient:
    """RAG 단계별 LLM 호출과 관측 지표를 한 경로에서 관리한다."""
    def __init__(self, endpoint: LLMEndpoint | None = None) -> None:
        """요청에 고정된 endpoint 또는 명시적으로 받은 snapshot을 사용한다."""
        endpoint = endpoint or get_active_endpoint()
        self.endpoint_key = endpoint.key
        self.model = endpoint.model
        self.supports_vision = endpoint.supports_vision
        self.client = OpenAI(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
        )

    def chat_completion(
        self,
        messages: list[dict[str, object]],
        temperature: float = 0.2,
        operation: str = "completion",
        response_format: dict[str, str] | None = None,
    ) -> str:
        """동기 응답을 생성하고 컨텍스트 초과만 축소 예산으로 재시도한다."""
        started_at = time.perf_counter()
        max_tokens = MAX_TOKENS_BY_OPERATION.get(operation, DEFAULT_MAX_TOKENS)
        context_retry_used = False
        try:
            while True:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        extra_body={"repetition_penalty": 1.15},
                        **({"response_format": response_format} if response_format else {}),
                    )
                    break
                except Exception as exc:
                    context_error = _context_length_error(exc)
                    if context_error is None:
                        raise
                    # 출력 예산 조정으로 복구하지 못하면 호출자가 입력을 축소한다.
                    if context_retry_used:
                        raise context_error from exc
                    reduced_max_tokens = _reduced_output_token_budget(
                        context_error,
                        max_tokens,
                    )
                    if reduced_max_tokens is None:
                        raise context_error from exc
                    logger.warning(
                        "Retrying LLM request with reduced output token budget: %s -> %s",
                        max_tokens,
                        reduced_max_tokens,
                        extra={"operation": operation},
                    )
                    context_retry_used = True
                    max_tokens = reduced_max_tokens
            content = response.choices[0].message.content or ""
        except Exception:
            LLM_REQUESTS.labels(operation=operation, mode="sync", status="error").inc()
            logger.exception("LLM request failed", extra={"operation": operation})
            raise
        else:
            if context_retry_used:
                LLM_CONTEXT_RECOVERIES.labels(
                    operation=operation,
                    strategy="output_budget",
                ).inc()
            LLM_REQUESTS.labels(operation=operation, mode="sync", status="success").inc()
            return content
        finally:
            LLM_DURATION.labels(operation=operation, mode="sync").observe(
                time.perf_counter() - started_at
            )

    def stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        operation: str = "answer",
    ) -> Iterator[str]:
        """첫 델타 전 컨텍스트 초과만 출력 예산을 줄여 스트림을 재시도한다."""
        started_at = time.perf_counter()
        first_token_recorded = False
        status = "success"
        max_tokens = MAX_TOKENS_BY_OPERATION.get(operation, DEFAULT_MAX_TOKENS)
        context_retry_used = False
        emitted_content = False
        try:
            while True:
                try:
                    stream = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        extra_body={"repetition_penalty": 1.15},
                        stream=True,
                    )
                    with stream:
                        for chunk in stream:
                            content = chunk.choices[0].delta.content or ""
                            if not content:
                                continue
                            if not first_token_recorded:
                                LLM_TIME_TO_FIRST_TOKEN.labels(operation=operation).observe(
                                    time.perf_counter() - started_at
                                )
                                first_token_recorded = True
                            emitted_content = True
                            yield content
                    break
                except Exception as exc:
                    context_error = _context_length_error(exc)
                    if context_error is None:
                        raise
                    # 이미 보낸 델타는 되돌릴 수 있어야 하므로 상위 생성기에 복구를 맡긴다.
                    if emitted_content or context_retry_used:
                        raise context_error from exc
                    reduced_max_tokens = _reduced_output_token_budget(
                        context_error,
                        max_tokens,
                    )
                    if reduced_max_tokens is None:
                        raise context_error from exc
                    logger.warning(
                        "Retrying streaming LLM request with reduced output token budget: %s -> %s",
                        max_tokens,
                        reduced_max_tokens,
                        extra={"operation": operation},
                    )
                    context_retry_used = True
                    max_tokens = reduced_max_tokens
            if context_retry_used:
                LLM_CONTEXT_RECOVERIES.labels(
                    operation=operation,
                    strategy="output_budget",
                ).inc()
        except GeneratorExit:
            status = "cancelled"
            raise
        except Exception:
            status = "error"
            logger.exception("Streaming LLM request failed", extra={"operation": operation})
            raise
        finally:
            LLM_REQUESTS.labels(operation=operation, mode="stream", status=status).inc()
            LLM_DURATION.labels(operation=operation, mode="stream").observe(
                time.perf_counter() - started_at
            )
