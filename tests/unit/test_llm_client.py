from types import SimpleNamespace

import pytest

from app.clients import llm_client
from app.clients.llm_client import ContextLengthExceededError, LLMClient
from app.config import LLMEndpoint


def _endpoint() -> LLMEndpoint:
    """클라이언트 초기화 검증에 사용할 immutable endpoint를 만든다."""
    return LLMEndpoint(
        key="vision",
        display_name="Vision model",
        base_url="http://model-b:9000/v1",
        api_key="key-b",
        model="model-b",
        supports_vision=True,
    )


def test_client_uses_explicit_endpoint_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """명시한 snapshot으로 OpenAI client가 초기화되는지 보장한다."""
    created: dict[str, str] = {}

    class FakeOpenAI:
        """OpenAI 초기화 인자를 기록하는 대역이다."""

        def __init__(self, *, base_url: str, api_key: str) -> None:
            """전달된 접속 정보를 기록한다."""
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient(_endpoint())

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"
    assert client.model == "model-b"
    assert client.supports_vision is True


def test_client_uses_runtime_active_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """snapshot을 생략하면 요청 문맥의 endpoint를 사용하는지 보장한다."""
    created: dict[str, str] = {}

    class FakeOpenAI:
        """활성 endpoint 접속 정보를 기록하는 대역이다."""

        def __init__(self, *, base_url: str, api_key: str) -> None:
            """전달된 접속 정보를 기록한다."""
            created.update(base_url=base_url, api_key=api_key)

    monkeypatch.setattr(llm_client, "get_active_endpoint", _endpoint)
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)

    client = LLMClient()

    assert created == {"base_url": "http://model-b:9000/v1", "api_key": "key-b"}
    assert client.endpoint_key == "vision"

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


def test_stream_completion_retries_context_overflow_raised_by_first_iteration() -> None:
    """스트림 생성 뒤 첫 순회에서 난 컨텍스트 초과도 델타 전에는 복구한다."""
    class FailingStream:
        """첫 순회에서 컨텍스트 초과를 내는 스트림 대역이다."""

        def __enter__(self):
            """스트림 컨텍스트 진입 시 자신을 반환한다."""
            return self

        def __exit__(self, *args) -> None:
            """검증용 스트림 종료를 정상 처리한다."""
            return None

        def __iter__(self):
            """첫 응답 조각 대신 컨텍스트 초과를 발생시킨다."""
            raise RuntimeError(CONTEXT_LENGTH_ERROR)

    class RecoveredStream:
        """출력 예산 축소 뒤 정상 조각을 돌려주는 스트림 대역이다."""

        def __enter__(self):
            """스트림 컨텍스트 진입 시 자신을 반환한다."""
            return self

        def __exit__(self, *args) -> None:
            """검증용 스트림 종료를 정상 처리한다."""
            return None

        def __iter__(self):
            """복구된 답변 조각을 순회한다."""
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="recovered answer")
                            )
                        ]
                    )
                ]
            )

    class Completions:
        """호출 순서에 따라 실패·복구 스트림을 제공한다."""

        def __init__(self) -> None:
            """호출별 출력 예산을 기록한다."""
            self.max_tokens: list[int] = []

        def create(self, **kwargs):
            """첫 호출은 순회 실패 스트림, 다음 호출은 정상 스트림을 반환한다."""
            self.max_tokens.append(kwargs["max_tokens"])
            return FailingStream() if len(self.max_tokens) == 1 else RecoveredStream()

    completions = Completions()
    result = list(
        _client_with_completions(completions).stream_chat_completion(
            [{"role": "user", "content": "question"}],
            operation="answer",
        )
    )

    assert result == ["recovered answer"]
    assert completions.max_tokens == [900, 883]


def test_context_error_without_token_counts_is_exposed_as_typed_error() -> None:
    """토큰 수가 없는 호환 서버 오류도 상위 입력 축소가 처리할 전용 오류로 바꾼다."""
    class ContextError(RuntimeError):
        """구조화된 오류 코드만 제공하는 서버 오류 대역이다."""

        body = {"error": {"code": "context_length_exceeded"}}

    class Completions:
        """컨텍스트 초과를 항상 반환하는 완료 API 대역이다."""

        def __init__(self) -> None:
            """호출 횟수를 초기화한다."""
            self.calls = 0

        def create(self, **kwargs):
            """토큰 수 없는 컨텍스트 초과를 반환한다."""
            self.calls += 1
            raise ContextError("request rejected")

    completions = Completions()
    with pytest.raises(ContextLengthExceededError):
        _client_with_completions(completions).chat_completion(
            [{"role": "user", "content": "question"}],
            operation="answer",
        )

    assert completions.calls == 1
