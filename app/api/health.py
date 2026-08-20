from fastapi import APIRouter, Response, status

from app.schemas.health import ReadinessResponse
from app.services.readiness_service import check_readiness

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """프로세스가 HTTP 요청에 응답할 수 있음을 알린다."""
    return {"status": "ok"}


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness_check(response: Response) -> ReadinessResponse:
    """필수 의존성 상태를 확인하고 준비되지 않으면 503을 반환한다."""
    readiness = check_readiness()
    if readiness.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return readiness
