from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import ensure_retrieval_writes_available, get_current_user, get_db
from app.models.user import User
from app.repositories import chat_repository
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.generator import generate_answer
from app.services.retriever import retrieve_chunks

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(ensure_retrieval_writes_available),
) -> ChatResponse:
    chunks = retrieve_chunks(db=db, owner_id=user.id, question=request.question)
    generated = generate_answer(question=request.question, chunks=chunks)

    session = chat_repository.create_session(
        db,
        owner_id=user.id,
        document_id=None,
        title=request.question[:80],
    )
    chat_repository.create_message(db, session.id, "user", request.question)
    chat_repository.create_message(
        db,
        session.id,
        "assistant",
        generated.answer,
        retrieved_chunk_ids=[chunk.chunk_id for chunk in chunks],
        metadata={"sources": [source.model_dump() for source in generated.sources]},
    )
    db.commit()

    return ChatResponse(answer=generated.answer, sources=generated.sources)
