from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.retrieval_config import SearchAlgorithmRecord
from app.repositories import retrieval_config_repository


class SearchAlgorithmNotFoundError(Exception):
    pass


class SearchAlgorithmChangeConflictError(Exception):
    pass


def activate_search_algorithm(db: Session, algorithm_key: str) -> SearchAlgorithmRecord:
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
