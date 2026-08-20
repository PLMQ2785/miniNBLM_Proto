from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.retrieval_config import SearchAlgorithmRecord
from app.repositories import retrieval_config_repository


class SearchAlgorithmNotFoundError(Exception):
    """요청한 검색 알고리즘이 없음을 관리자 API에 알린다."""
    pass


class SearchAlgorithmChangeConflictError(Exception):
    """유지보수 중 알고리즘 변경을 막기 위한 충돌을 알린다."""
    pass


def activate_search_algorithm(db: Session, algorithm_key: str) -> SearchAlgorithmRecord:
    """유지보수 잠금을 확인하고 활성 검색 알고리즘을 원자적으로 바꾼다."""
    configuration = retrieval_config_repository.get_configuration(db, for_update=True)
    if configuration.maintenance_mode:
        raise SearchAlgorithmChangeConflictError("Retrieval maintenance is in progress")

    algorithm = retrieval_config_repository.get_search_algorithm(db, algorithm_key)
    if algorithm is None:
        raise SearchAlgorithmNotFoundError

    configuration.active_search_algorithm_key = algorithm.key
    configuration.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(algorithm)
    return algorithm
