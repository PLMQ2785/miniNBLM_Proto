from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin_retrieval, admin_users, auth, chat, documents, health, language_models, metrics
from app.config import settings
from app.observability import RequestObservabilityMiddleware, configure_logging
from app.request_limits import RequestBodyLimitMiddleware
from app.services.runtime_service import initialize_runtime


@asynccontextmanager
async def lifespan(_: FastAPI):
    """API 수신 전 로깅과 중단 작업 복구를 준비한다."""
    # 요청 수신 전에 저장된 작업을 복구한다.
    configure_logging(settings.log_level)
    initialize_runtime()
    yield


app = FastAPI(title="PDF RAG Assistant API", lifespan=lifespan)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
)
app.add_middleware(RequestObservabilityMiddleware)


@app.middleware("http")
async def prevent_stale_web_assets(request, call_next):
    """웹 셸과 정적 자산이 이전 배포본으로 남지 않게 한다."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.include_router(language_models.router)
app.include_router(admin_retrieval.router)
app.include_router(admin_users.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(health.router)
app.include_router(metrics.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False, response_class=FileResponse)
def web_ui() -> FileResponse:
    """브라우저 진입점인 웹 셸을 반환한다."""
    return FileResponse(STATIC_DIR / "index.html")
