import logging
import time
from collections.abc import Iterator

from openai import OpenAI

from app.config import settings
from app.observability import LLM_DURATION, LLM_REQUESTS, LLM_TIME_TO_FIRST_TOKEN


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


class VLLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or settings.vllm_model
        self.client = OpenAI(
            base_url=base_url or settings.vllm_base_url,
            api_key=api_key or settings.vllm_api_key,
        )

    def chat_completion(
        self,
        messages: list[dict[str, object]],
        temperature: float = 0.2,
        operation: str = "completion",
        response_format: dict[str, str] | None = None,
    ) -> str:
        started_at = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=MAX_TOKENS_BY_OPERATION.get(operation, DEFAULT_MAX_TOKENS),
                extra_body={"repetition_penalty": 1.15},
                **({"response_format": response_format} if response_format else {}),
            )
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
        try:
            with self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=MAX_TOKENS_BY_OPERATION.get(operation, DEFAULT_MAX_TOKENS),
                extra_body={"repetition_penalty": 1.15},
                stream=True,
            ) as stream:
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
