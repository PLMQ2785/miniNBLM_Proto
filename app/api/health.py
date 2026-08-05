from fastapi import APIRouter, Response, status

from app.schemas.health import ReadinessResponse
from app.services.readiness_service import check_readiness

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness_check(response: Response) -> ReadinessResponse:
    readiness = check_readiness()
    if readiness.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return readiness
