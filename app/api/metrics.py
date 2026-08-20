from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus가 수집할 최신 애플리케이션 지표를 반환한다."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
