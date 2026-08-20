import logging
import re
import time
from collections.abc import Iterator

from openai import OpenAI

from app.config import settings
from app.observability import LLM_DURATION, LLM_REQUESTS, LLM_TIME_TO_FIRST_TOKEN
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
CONTEXT_RETRY_TOKEN_MARGIN = 16
MIN_CONTEXT_RETRY_OUTPUT_TOKENS = 128


def _reduced_output_token_budget(exc: Exception, current_max_tokens: int) -> int | None:
    match = CONTEXT_LENGTH_ERROR_PATTERN.search(str(exc))
    if match is None:
        return None
    context_limit = int(match.group("limit").replace(",", ""))
    input_tokens = int(match.group("input").replace(",", ""))
    # Leave a small margin for tokenizer differences reported by compatible endpoints.
    available_output_tokens = context_limit - input_tokens - CONTEXT_RETRY_TOKEN_MARGIN
    if (
        available_output_tokens < MIN_CONTEXT_RETRY_OUTPUT_TOKENS
        or available_output_tokens >= current_max_tokens
    ):
        return None
    return available_output_tokens


class LLMClient:
    def __init__(self, endpoint_key: str | None = None) -> None:
        endpoint = settings.get_llm_endpoint(endpoint_key) if endpoint_key else get_active_endpoint()
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
                    # Retry only before a response exists, and never more than once.
                    if context_retry_used:
                        raise
                    reduced_max_tokens = _reduced_output_token_budget(exc, max_tokens)
                    if reduced_max_tokens is None:
                        raise
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
        started_at = time.perf_counter()
        first_token_recorded = False
        status = "success"
        max_tokens = MAX_TOKENS_BY_OPERATION.get(operation, DEFAULT_MAX_TOKENS)
        context_retry_used = False
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
                    break
                except Exception as exc:
                    # A stream can be retried safely only before the first delta.
                    if context_retry_used:
                        raise
                    reduced_max_tokens = _reduced_output_token_budget(exc, max_tokens)
                    if reduced_max_tokens is None:
                        raise
                    logger.warning(
                        "Retrying streaming LLM request with reduced output token budget: %s -> %s",
                        max_tokens,
                        reduced_max_tokens,
                        extra={"operation": operation},
                    )
                    context_retry_used = True
                    max_tokens = reduced_max_tokens
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
                    yield content
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
