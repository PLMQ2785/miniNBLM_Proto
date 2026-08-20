from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.clients import llm_client
from app.clients.llm_client import LLMClient
from app.services import language_model_service
from app.config import LLMConfiguration, Settings


def _settings(*, default: str = "primary", vision_mode: str = "disabled") -> Settings:
    """엔드포인트 선택 검증에 쓸 설정을 만든다."""
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
    """지정한 키의 엔드포인트로 클라이언트가 초기화되는지 보장한다."""
    created: dict[str, str] = {}

    class FakeOpenAI:
        """OpenAI 초기화 인자를 기록하는 대역이다."""
        def __init__(self, *, base_url: str, api_key: str) -> None:
            """전달된 접속 정보를 기록한다."""
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(llm_client, "settings", _settings())
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient("vision")

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"
    assert client.model == "model-b"
    assert client.supports_vision is True

def test_client_uses_runtime_active_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """키를 생략하면 런타임 활성 엔드포인트를 사용하는지 보장한다."""
    configured = _settings()
    created: dict[str, str] = {}

    class FakeOpenAI:
        """활성 엔드포인트 접속 정보를 기록하는 대역이다."""
        def __init__(self, *, base_url: str, api_key: str) -> None:
            """전달된 접속 정보를 기록한다."""
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
    """존재하지 않는 기본 엔드포인트 설정을 거부하는지 보장한다."""
    with pytest.raises(ValidationError, match="default_endpoint"):
        _settings(default="missing")


def test_captioning_requires_vision_capable_default_endpoint() -> None:
    """캡션 모드는 시각 지원 기본 엔드포인트만 허용하는지 보장한다."""
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
    """완료 API 대역을 주입한 LLM 클라이언트를 만든다."""
    client = object.__new__(LLMClient)
    client.model = "model-a"
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )
    return client


def test_sync_completion_retries_context_overflow_with_available_budget() -> None:
    """동기 호출이 컨텍스트 초과 시 남은 예산으로 한 번 재시도하는지 보장한다."""
    class Completions:
        """동기 완료 호출의 토큰 예산과 재시도를 기록한다."""
        def __init__(self) -> None:
            """호출별 최대 토큰 값을 모은다."""
            self.max_tokens: list[int] = []

        def create(self, **kwargs):
            """첫 호출만 컨텍스트 초과를 내고 다음 호출은 답을 돌려준다."""
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
    """첫 스트림 조각 전 컨텍스트 초과만 예산을 줄여 재시도하는지 보장한다."""
    class Stream:
        """재시도 뒤 반환할 컨텍스트 관리자형 스트림 대역이다."""
        def __enter__(self):
            """스트림 컨텍스트 진입 시 자신을 돌려준다."""
            return self

        def __exit__(self, *args) -> None:
            """스트림 컨텍스트 종료를 정상 처리한다."""
            return None

        def __iter__(self):
            """검증용 응답 조각을 순회한다."""
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
        """스트리밍 완료 호출의 토큰 예산과 재시도를 기록한다."""
        def __init__(self) -> None:
            """호출별 최대 토큰 값을 모은다."""
            self.max_tokens: list[int] = []

        def create(self, **kwargs):
            """첫 호출만 컨텍스트 초과를 내고 다음 호출은 스트림을 돌려준다."""
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
    """컨텍스트 초과가 아닌 오류는 재시도하지 않고 전파하는지 보장한다."""
    class Completions:
        """일반 오류 호출 횟수를 기록하는 완료 API 대역이다."""
        def __init__(self) -> None:
            """호출 횟수를 초기화한다."""
            self.calls = 0

        def create(self, **kwargs):
            """일반 서비스 오류를 항상 발생시킨다."""
            self.calls += 1
            raise RuntimeError("service unavailable")

    completions = Completions()
    with pytest.raises(RuntimeError, match="service unavailable"):
        _client_with_completions(completions).chat_completion(
            [{"role": "user", "content": "question"}],
            operation="answer",
        )

    assert completions.calls == 1
