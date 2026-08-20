from typing import Literal

from pydantic import BaseModel


class ReadinessComponent(BaseModel):
    """준비 상태 API가 반환하는 개별 의존성 점검 경계다."""
    status: Literal["ok", "error"]
    latency_ms: int
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """준비 상태 API의 전체 결과 경계다."""
    status: Literal["ready", "not_ready"]
    components: dict[str, ReadinessComponent]
