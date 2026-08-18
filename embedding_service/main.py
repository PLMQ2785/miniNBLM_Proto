from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentence_transformers import SentenceTransformer


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str | None = None


class QueryEmbeddingRequest(BaseModel):
    text: str = Field(min_length=1)


class QueriesEmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=5)


class DocumentsEmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    dimension: int


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(
        settings.embedding_model,
        device=settings.embedding_device or None,
    )


app = FastAPI(title="BGE-M3 Embedding Service")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/embed/query", response_model=EmbeddingResponse)
def embed_query(request: QueryEmbeddingRequest) -> EmbeddingResponse:
    embedding = get_model().encode([request.text], normalize_embeddings=True)
    values = embedding.tolist()
    return EmbeddingResponse(embeddings=values, dimension=len(values[0]))


@app.post("/embed/queries", response_model=EmbeddingResponse)
def embed_queries(request: QueriesEmbeddingRequest) -> EmbeddingResponse:
    embeddings = get_model().encode(request.texts, normalize_embeddings=True)
    values = embeddings.tolist()
    return EmbeddingResponse(embeddings=values, dimension=len(values[0]))


@app.post("/embed/documents", response_model=EmbeddingResponse)
def embed_documents(request: DocumentsEmbeddingRequest) -> EmbeddingResponse:
    embeddings = get_model().encode(request.texts, normalize_embeddings=True)
    values = embeddings.tolist()
    return EmbeddingResponse(embeddings=values, dimension=len(values[0]))
