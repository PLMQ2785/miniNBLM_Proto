from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.clients import llm_client
from app.clients.llm_client import LLMClient
from app.services import language_model_service
from app.config import LLMConfiguration, Settings


def _settings(*, default: str = "primary", vision_mode: str = "disabled") -> Settings:
    return Settings(
        _env_file=None,
        llm_configuration=LLMConfiguration(
            default_endpoint=default,
            endpoints=[
                {
                    "key": "primary",
                    "display_name": "Primary text model",
                    "base_url": "http://model-a:8000/v1/",
                    "api_key": "key-a",
                    "model": "model-a",
                    "supports_vision": False,
                },
                {
                    "key": "vision",
                    "display_name": "Vision model",
                    "base_url": "http://model-b:9000/v1",
                    "api_key": "key-b",
                    "model": "model-b",
                    "supports_vision": True,
                },
            ],
        ),
        vision_caption_mode=vision_mode,
    )


def test_client_selects_configured_endpoint_by_key(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(llm_client, "settings", _settings())
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient("vision")

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"
    assert client.model == "model-b"
    assert client.supports_vision is True

def test_client_uses_runtime_active_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = _settings()
    created: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(
        language_model_service,
        "get_active_endpoint",
        lambda: configured.get_llm_endpoint("vision"),
    )
    monkeypatch.setattr(llm_client, "get_active_endpoint", language_model_service.get_active_endpoint)
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient()

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"


def test_default_endpoint_must_exist() -> None:
    with pytest.raises(ValidationError, match="default_endpoint"):
        _settings(default="missing")


def test_captioning_requires_vision_capable_default_endpoint() -> None:
    with pytest.raises(ValidationError, match="must support vision"):
        _settings(vision_mode="risk_only")

    configured = _settings(default="vision", vision_mode="risk_only")
    assert configured.get_llm_endpoint().key == "vision"


CONTEXT_LENGTH_ERROR = (
    "This model's maximum context length is 8192 tokens. "
    "However, you requested 900 output tokens and your prompt contains at least "
    "7293 input tokens, for a total of at least 8193 tokens."
)


def _client_with_completions(completions) -> LLMClient:
    client = object.__new__(LLMClient)
    client.model = "model-a"
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )
    return client


def test_sync_completion_retries_context_overflow_with_available_budget() -> None:
    class Completions:
        def __init__(self) -> None:
            self.max_tokens: list[int] = []

        def create(self, **kwargs):
            self.max_tokens.append(kwargs["max_tokens"])
            if len(self.max_tokens) == 1:
                raise RuntimeError(CONTEXT_LENGTH_ERROR)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            )

    completions = Completions()
    result = _client_with_completions(completions).chat_completion(
        [{"role": "user", "content": "question"}],
        operation="answer",
    )

    assert result == "answer"
    assert completions.max_tokens == [900, 883]


def test_stream_completion_retries_before_first_delta_on_context_overflow() -> None:
    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def __iter__(self):
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="streamed answer")
                            )
                        ]
                    )
                ]
            )

    class Completions:
        def __init__(self) -> None:
            self.max_tokens: list[int] = []

        def create(self, **kwargs):
            self.max_tokens.append(kwargs["max_tokens"])
            if len(self.max_tokens) == 1:
                raise RuntimeError(CONTEXT_LENGTH_ERROR)
            return Stream()

    completions = Completions()
    deltas = list(
        _client_with_completions(completions).stream_chat_completion(
            [{"role": "user", "content": "question"}],
            operation="answer",
        )
    )

    assert deltas == ["streamed answer"]
    assert completions.max_tokens == [900, 883]


def test_non_context_error_is_not_retried() -> None:
    class Completions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError("service unavailable")

    completions = Completions()
    with pytest.raises(RuntimeError, match="service unavailable"):
        _client_with_completions(completions).chat_completion(
            [{"role": "user", "content": "question"}],
            operation="answer",
        )

    assert completions.calls == 1
