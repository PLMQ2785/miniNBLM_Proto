from functools import lru_cache
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentence_transformers import CrossEncoder, SentenceTransformer
import torch
from torch import nn


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str | None = None
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_model_revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    reranker_device: str | None = None
    reranker_dtype: Literal["auto", "float16", "bfloat16", "float32"] = "auto"
    reranker_batch_size: int = Field(default=16, ge=1, le=128)
    reranker_max_length: int = Field(default=512, ge=64, le=2048)


class QueryEmbeddingRequest(BaseModel):
    text: str = Field(min_length=1)


class QueriesEmbeddingRequest(BaseModel):
    # The API client batches to this service limit.
    texts: list[str] = Field(min_length=1, max_length=5)


class DocumentsEmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class RerankPair(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    passage: str = Field(min_length=1, max_length=16000)


class RerankRequest(BaseModel):
    pairs: list[RerankPair] = Field(min_length=1, max_length=256)


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    dimension: int


class RerankResponse(BaseModel):
    scores: list[float]


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Load once on the first embedding request; /health only checks the process.
@lru_cache
def get_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(
        settings.embedding_model,
        device=settings.embedding_device or None,
    )


# The heavier cross-encoder stays unloaded unless /rerank is used.
@lru_cache
def get_reranker() -> CrossEncoder:
    settings = get_settings()
    model_kwargs = (
        {}
        if settings.reranker_dtype == "auto"
        else {"dtype": getattr(torch, settings.reranker_dtype)}
    )
    return CrossEncoder(
        settings.reranker_model,
        max_length=settings.reranker_max_length,
        activation_fn=nn.Sigmoid(),
        device=settings.reranker_device or settings.embedding_device or None,
        revision=settings.reranker_model_revision,
        model_kwargs=model_kwargs,
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


@app.post("/rerank", response_model=RerankResponse)
def rerank(request: RerankRequest) -> RerankResponse:
    pairs = [(pair.query, pair.passage) for pair in request.pairs]
    scores = get_reranker().predict(
        pairs,
        batch_size=get_settings().reranker_batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return RerankResponse(scores=[float(score) for score in scores])
