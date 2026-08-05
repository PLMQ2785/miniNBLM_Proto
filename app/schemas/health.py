from typing import Literal

from pydantic import BaseModel


class ReadinessComponent(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: int
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    components: dict[str, ReadinessComponent]
