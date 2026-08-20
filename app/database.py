from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """프로젝트 ORM 모델이 공유하는 선언 기반 클래스다."""
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """요청 단위 세션을 열고 응답 뒤 반드시 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
