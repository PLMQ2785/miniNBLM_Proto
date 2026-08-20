from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - SQLAlchemy 관계 전체를 등록한다.
from app.config import settings
from app.database import SessionLocal
from app.evaluation.fixture import (
    EvaluationCase,
    RetrievalEvaluationFixture,
    load_evaluation_fixture,
)
from app.evaluation.metrics import (
    RankedReference,
    aggregate_scores,
    percentile,
    score_retrieval,
)
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.user import User
from app.repositories import document_repository, retrieval_config_repository
from app.retrieval_presets import BUILT_IN_PRESETS
from app.search_algorithms import SearchAlgorithmKey
from app.services.document_processor import process_document
from app.services.retriever import RetrievedChunk, retrieve_chunks
from app.services.query_rewriter import EvidenceGoal


DEFAULT_FIXTURE = Path("evaluation/retrieval_fall_prevention.json")
DEFAULT_OUTPUT_DIR = Path("benchmark_results/retrieval")


def _positive_integer(value: str) -> int:
    """양의 정수 명령행 값을 검증한다."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _non_negative_integer(value: str) -> int:
    """0 이상의 정수 명령행 값을 검증한다."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be at least 0")
    return parsed


def _unit_interval(value: str) -> float:
    """0과 1 사이의 실수 명령행 값을 검증한다."""
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return parsed


def _resolve_documents(
    fixture_path: Path,
    fixture: RetrievalEvaluationFixture,
) -> list[tuple[str, Path]]:
    """픽스처 기준으로 평가 문서 경로를 해석하고 확인한다."""
    resolved = []
    for document in fixture.documents:
        path = Path(document.path)
        if not path.is_absolute():
            path = fixture_path.parent / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Evaluation document not found: {path}")
        resolved.append((document.title, path))
    return resolved


def _select_keys(requested: list[str] | None, available: list[str], label: str) -> list[str]:
    """요청한 키가 허용 목록에 있는지 확인하고 중복을 제거한다."""
    if not requested:
        return available
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"Unknown {label}: {', '.join(unknown)}")
    return list(dict.fromkeys(requested))


def _create_corpus(db: Session, documents: list[tuple[str, Path]]) -> tuple[User, list[Document]]:
    """평가 전용 사용자와 문서 행을 만들어 코퍼스를 격리한다."""
    user = User(
        username=f"retrieval-benchmark-{uuid.uuid4().hex}",
        password_hash="benchmark-account-has-no-login-secret",
        role="user",
    )
    db.add(user)
    db.flush()
    rows = [
        document_repository.create_document(
            db,
            owner_id=user.id,
            title=title,
            file_path=str(path),
            mime_type="application/pdf",
        )
        for title, path in documents
    ]
    db.commit()
    return user, rows


def _delete_corpus(db: Session, user_id: int) -> None:
    """평가 사용자에 속한 문서와 계정을 함께 제거한다."""
    db.rollback()
    documents = list(db.scalars(select(Document).where(Document.owner_id == user_id)))
    for document in documents:
        db.delete(document)
    db.flush()
    user = db.get(User, user_id)
    if user is not None:
        db.delete(user)
    db.commit()


def _references(results: list[RetrievedChunk]) -> list[RankedReference]:
    """검색 청크를 순위 지표 계산용 참조로 변환한다."""
    return [
        RankedReference(
            document=result.document_title,
            page_start=result.page_start,
            page_end=result.page_end,
        )
        for result in results
    ]


def _relevant_sources(case: EvaluationCase) -> set[tuple[str, int]]:
    """사례의 정답 출처를 비교용 키 집합으로 만든다."""
    return {(source.document, source.page) for source in case.relevant_sources}


def _case_result(
    db: Session,
    owner_id: int,
    case: EvaluationCase,
    retrieval_top_k: int,
    evaluation_k: int,
    warmup: int,
    iterations: int,
) -> tuple[dict[str, Any], list[float]]:
    """한 사례를 예열·반복 실행해 품질과 지연 시간을 측정한다."""
    goals = tuple(
        EvidenceGoal(f"g{index}", query, (query,))
        for index, query in enumerate(case.retrieval_queries or [case.question], start=1)
    )
    for _ in range(warmup):
        retrieve_chunks(
            db,
            owner_id=owner_id,
            question=case.question,
            top_k=retrieval_top_k,
            goals=goals,
        )

    latency_samples = []
    first_results: list[RetrievedChunk] | None = None
    for _ in range(iterations):
        started = time.perf_counter()
        results = retrieve_chunks(
            db,
            owner_id=owner_id,
            question=case.question,
            top_k=retrieval_top_k,
            goals=goals,
        )
        latency_samples.append((time.perf_counter() - started) * 1000)
        if first_results is None:
            first_results = results

    if first_results is None:
        raise ValueError("iterations must be at least 1")
    score = score_retrieval(
        _references(first_results),
        _relevant_sources(case),
        evaluation_k,
    )
    result = {
        "case_id": case.case_id,
        "question": case.question,
        "retrieval_queries": case.retrieval_queries or [case.question],
        "relevant_sources": [source.model_dump() for source in case.relevant_sources],
        "retrieved": [
            {
                "rank": rank,
                "document": chunk.document_title,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "score": chunk.score,
            }
            for rank, chunk in enumerate(first_results, start=1)
        ],
        "recall_at_k": score.recall_at_k,
        "hit_at_k": score.hit_at_k,
        "reciprocal_rank": score.reciprocal_rank,
        "first_relevant_rank": score.first_relevant_rank,
        "latency_p50_ms": percentile(latency_samples, 0.50),
        "latency_p95_ms": percentile(latency_samples, 0.95),
    }
    return result, latency_samples


def _evaluate_algorithm(
    db: Session,
    owner_id: int,
    fixture: RetrievalEvaluationFixture,
    algorithm_key: str,
    retrieval_top_k: int,
    evaluation_k: int,
    warmup: int,
    iterations: int,
) -> dict[str, Any]:
    """검색 알고리즘 하나를 모든 사례에 적용해 결과를 집계한다."""
    if warmup < 0:
        raise ValueError("warmup must be non-negative")
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if evaluation_k < 1:
        raise ValueError("evaluation_k must be at least 1")

    configuration = retrieval_config_repository.get_configuration(db)
    configuration.active_search_algorithm_key = algorithm_key
    db.commit()

    case_results = []
    latency_samples = []
    scores = []
    for case in fixture.cases:
        case_result, case_latencies = _case_result(
            db,
            owner_id,
            case,
            retrieval_top_k,
            evaluation_k,
            warmup,
            iterations,
        )
        case_results.append(case_result)
        latency_samples.extend(case_latencies)
        scores.append(
            score_retrieval(
                [
                    RankedReference(
                        document=row["document"],
                        page_start=row["page_start"],
                        page_end=row["page_end"],
                    )
                    for row in case_result["retrieved"]
                ],
                _relevant_sources(case),
                evaluation_k,
            )
        )

    return {
        "algorithm": algorithm_key,
        "retrieval_top_k": retrieval_top_k,
        "evaluation_k": evaluation_k,
        "metrics": aggregate_scores(scores, latency_samples),
        "cases": case_results,
    }


def run_benchmark(
    fixture_path: Path,
    *,
    preset_keys: list[str] | None = None,
    algorithm_keys: list[str] | None = None,
    warmup: int = 1,
    iterations: int = 3,
    evaluation_k: int = 5,
) -> dict[str, Any]:
    """임시 코퍼스로 검색 조합을 평가하고 전역 설정과 데이터를 원복한다."""
    fixture_path = fixture_path.resolve()
    fixture = load_evaluation_fixture(fixture_path)
    documents = _resolve_documents(fixture_path, fixture)
    available_presets = [preset.key for preset in BUILT_IN_PRESETS]
    available_algorithms = [algorithm.value for algorithm in SearchAlgorithmKey]
    selected_presets = _select_keys(preset_keys, available_presets, "presets")
    selected_algorithms = _select_keys(algorithm_keys, available_algorithms, "algorithms")

    started_at = datetime.now(UTC)
    db = SessionLocal()
    user: User | None = None
    configuration = retrieval_config_repository.get_configuration(db)
    original_configuration = (
        configuration.active_preset_key,
        configuration.active_search_algorithm_key,
        configuration.index_version,
    )
    # 벤치마크가 빌린 전역 검색 설정은 finally에서 되돌린다.
    preset_results = []
    try:
        user, corpus_documents = _create_corpus(db, documents)
        for preset_index, preset_key in enumerate(selected_presets, start=1):
            preset = retrieval_config_repository.get_preset(db, preset_key)
            if preset is None:
                raise RuntimeError(f"Preset is missing from the database: {preset_key}")

            # 각 프리셋은 같은 임시 코퍼스에 새 인덱스 버전을 사용한다.
            target_index_version = original_configuration[2] + preset_index
            indexing_started = time.perf_counter()
            for document in corpus_documents:
                succeeded = process_document(
                    document.id,
                    preset_key=preset_key,
                    index_version=target_index_version,
                    reset_existing=preset_index > 1,
                )
                if not succeeded:
                    raise RuntimeError(
                        f"Evaluation document indexing failed: document_id={document.id}, "
                        f"preset={preset_key}"
                    )
            indexing_ms = (time.perf_counter() - indexing_started) * 1000

            db.expire_all()
            configuration = retrieval_config_repository.get_configuration(db)
            configuration.active_preset_key = preset_key
            configuration.index_version = target_index_version
            db.commit()
            chunk_count = db.scalar(
                select(func.count())
                .select_from(Chunk)
                .join(Document, Document.id == Chunk.document_id)
                .where(Document.owner_id == user.id)
            )

            algorithms = [
                _evaluate_algorithm(
                    db,
                    owner_id=user.id,
                    fixture=fixture,
                    algorithm_key=algorithm_key,
                    retrieval_top_k=preset.top_k,
                    evaluation_k=evaluation_k,
                    warmup=warmup,
                    iterations=iterations,
                )
                for algorithm_key in selected_algorithms
            ]
            preset_results.append(
                {
                    "preset": preset_key,
                    "chunk_size_chars": preset.chunk_size_chars,
                    "chunk_overlap_chars": preset.chunk_overlap_chars,
                    "top_k": preset.top_k,
                    "chunk_count": int(chunk_count or 0),
                    "indexing_ms": indexing_ms,
                    "algorithms": algorithms,
                }
            )
    finally:
        # 평가 데이터와 설정이 다음 실행에 남지 않게 모두 정리한다.
        try:
            configuration = retrieval_config_repository.get_configuration(db)
            configuration.active_preset_key = original_configuration[0]
            configuration.active_search_algorithm_key = original_configuration[1]
            configuration.index_version = original_configuration[2]
            db.commit()
            if user is not None:
                _delete_corpus(db, user.id)
        finally:
            db.close()

    completed_at = datetime.now(UTC)
    return {
        "schema_version": 1,
        "fixture": {
            "name": fixture.name,
            "path": str(fixture_path),
            "sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            "case_count": len(fixture.cases),
            "document_count": len(fixture.documents),
            "documents": [
                {
                    "title": title,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for title, path in documents
            ],
        },
        "run": {
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": (completed_at - started_at).total_seconds(),
            "warmup_per_case": warmup,
            "iterations_per_case": iterations,
            "evaluation_k": evaluation_k,
        },
        "presets": preset_results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """검색 평가 결과를 비교용 마크다운 표로 렌더링한다."""
    lines = [
        f"# Retrieval Benchmark: {report['fixture']['name']}",
        "",
        f"- Completed: `{report['run']['completed_at']}`",
        f"- Cases: `{report['fixture']['case_count']}`",
        f"- Iterations per case: `{report['run']['iterations_per_case']}`",
        f"- Evaluation cutoff: `K={report['run']['evaluation_k']}`",
        "",
        "| Preset | Algorithm | Chunks | Recall@K | Hit rate@K | MRR@K | p50 ms | p95 ms | Index ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for preset in report["presets"]:
        for algorithm in preset["algorithms"]:
            metrics = algorithm["metrics"]
            lines.append(
                f"| {preset['preset']} | {algorithm['algorithm']} | {preset['chunk_count']} | "
                f"{metrics['recall_at_k']:.3f} | {metrics['hit_rate_at_k']:.3f} | "
                f"{metrics['mrr_at_k']:.3f} | {metrics['latency_p50_ms']:.2f} | "
                f"{metrics['latency_p95_ms']:.2f} | {preset['indexing_ms']:.2f} |"
            )
    lines.append("")
    return "\n".join(lines)


def _quality_failures(report: dict[str, Any], minimum_recall: float) -> list[str]:
    """최소 재현율을 넘지 못한 프리셋과 알고리즘을 나열한다."""
    return [
        f"{preset['preset']}/{algorithm['algorithm']}={algorithm['metrics']['recall_at_k']:.3f}"
        for preset in report["presets"]
        for algorithm in preset["algorithms"]
        if algorithm["metrics"]["recall_at_k"] < minimum_recall
    ]


def _parse_args() -> argparse.Namespace:
    """검색 벤치마크 명령행 옵션을 해석한다."""
    parser = argparse.ArgumentParser(description="Benchmark retrieval quality across presets and algorithms")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--preset", action="append", dest="presets")
    parser.add_argument("--algorithm", action="append", dest="algorithms")
    parser.add_argument("--warmup", type=_non_negative_integer, default=1)
    parser.add_argument("--iterations", type=_positive_integer, default=3)
    parser.add_argument("--evaluation-k", type=_positive_integer, default=5)
    parser.add_argument("--minimum-recall", type=_unit_interval, default=0.0)
    return parser.parse_args()


def main() -> int:
    """검색 벤치마크를 실행하고 보고서와 품질 종료 코드를 낸다."""
    args = _parse_args()
    report = run_benchmark(
        args.fixture,
        preset_keys=args.presets,
        algorithm_keys=args.algorithms,
        warmup=args.warmup,
        iterations=args.iterations,
        evaluation_k=args.evaluation_k,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base_path = args.output_dir / f"retrieval-benchmark-{timestamp}"
    json_path = base_path.with_suffix(".json")
    markdown_path = base_path.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(markdown_path.read_text(encoding="utf-8"))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")

    failures = _quality_failures(report, args.minimum_recall)
    if failures:
        print(
            f"Recall threshold {args.minimum_recall:.3f} failed: {', '.join(failures)}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
