from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentence_transformers import SentenceTransformer


class Settings(BaseSettings):
    """임베딩 API의 모델과 실행 장치를 환경 변수에서 읽는다."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str | None = None


class QueryEmbeddingRequest(BaseModel):
    """단일 검색 질의를 임베딩하도록 전달한다."""
    text: str = Field(min_length=1)


class QueriesEmbeddingRequest(BaseModel):
    """여러 검색 질의를 제한된 묶음으로 전달한다."""
    # API 클라이언트의 요청 묶음 크기와 맞춘다.
    texts: list[str] = Field(min_length=1, max_length=5)


class DocumentsEmbeddingRequest(BaseModel):
    """문서 본문 묶음을 임베딩하도록 전달한다."""
    texts: list[str] = Field(min_length=1)


class EmbeddingResponse(BaseModel):
    """임베딩 벡터와 차원을 API 응답으로 반환한다."""
    embeddings: list[list[float]]
    dimension: int


@lru_cache
def get_settings() -> Settings:
    """환경 설정을 프로세스에서 한 번만 생성한다."""
    return Settings()


# 상태 확인은 모델을 건드리지 않고 첫 임베딩 요청에서만 한 번 적재한다.
@lru_cache
def get_model() -> SentenceTransformer:
    """첫 임베딩 요청 시 모델을 지연 적재해 재사용한다."""
    settings = get_settings()
    return SentenceTransformer(
        settings.embedding_model,
        device=settings.embedding_device or None,
    )


app = FastAPI(title="BGE-M3 Embedding Service")


@app.get("/health")
def health_check() -> dict[str, str]:
    """모델 적재 없이 서비스 프로세스의 상태를 확인한다."""
    return {"status": "ok"}


@app.post("/embed/query", response_model=EmbeddingResponse)
def embed_query(request: QueryEmbeddingRequest) -> EmbeddingResponse:
    """단일 검색 질의를 정규화된 벡터로 변환한다."""
    embedding = get_model().encode([request.text], normalize_embeddings=True)
    values = embedding.tolist()
    return EmbeddingResponse(embeddings=values, dimension=len(values[0]))


@app.post("/embed/queries", response_model=EmbeddingResponse)
def embed_queries(request: QueriesEmbeddingRequest) -> EmbeddingResponse:
    """여러 검색 질의를 정규화된 벡터로 변환한다."""
    embeddings = get_model().encode(request.texts, normalize_embeddings=True)
    values = embeddings.tolist()
    return EmbeddingResponse(embeddings=values, dimension=len(values[0]))


@app.post("/embed/documents", response_model=EmbeddingResponse)
def embed_documents(request: DocumentsEmbeddingRequest) -> EmbeddingResponse:
    """문서 본문들을 정규화된 벡터로 변환한다."""
    embeddings = get_model().encode(request.texts, normalize_embeddings=True)
    values = embeddings.tolist()
    return EmbeddingResponse(embeddings=values, dimension=len(values[0]))
