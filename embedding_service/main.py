from functools import lru_cache
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentence_transformers import CrossEncoder, SentenceTransformer
import torch
from torch import nn


class Settings(BaseSettings):
    """임베딩 API의 모델과 실행 장치를 환경 변수에서 읽는다."""
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
    """단일 검색 질의를 임베딩하도록 전달한다."""
    text: str = Field(min_length=1)


class QueriesEmbeddingRequest(BaseModel):
    """여러 검색 질의를 제한된 묶음으로 전달한다."""
    # API 클라이언트의 요청 묶음 크기와 맞춘다.
    texts: list[str] = Field(min_length=1, max_length=5)


class DocumentsEmbeddingRequest(BaseModel):
    """문서 본문 묶음을 임베딩하도록 전달한다."""
    texts: list[str] = Field(min_length=1)


class RerankPair(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    passage: str = Field(min_length=1, max_length=16000)


class RerankRequest(BaseModel):
    pairs: list[RerankPair] = Field(min_length=1, max_length=256)


class EmbeddingResponse(BaseModel):
    """임베딩 벡터와 차원을 API 응답으로 반환한다."""
    embeddings: list[list[float]]
    dimension: int


class RerankResponse(BaseModel):
    scores: list[float]


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
