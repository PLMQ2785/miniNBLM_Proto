from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - SQLAlchemy 관계를 등록한다.
from app.config import settings
from app.database import SessionLocal
from app.evaluation.reasoning_fixture import (
    ReasoningCase,
    ReasoningDocument,
    ReasoningEvaluationFixture,
    load_reasoning_fixture,
)
from app.models.document import Document
from app.models.page import DocumentPage
from app.models.user import User
from app.repositories import document_repository, retrieval_config_repository
from app.retrieval_presets import BUILT_IN_PRESETS
from app.search_algorithms import SearchAlgorithmKey
from app.services.document_processor import process_document
from app.services.evidence_coverage import build_evidence_matrix, complete_evidence_coverage
from app.services.generator import (
    EMPTY_CONTEXT_ANSWER,
    INSUFFICIENT_EVIDENCE_ANSWER,
    VISUAL_EVIDENCE_LIMIT_ANSWER,
    generate_answer,
)
from app.services.query_rewriter import plan_retrieval_queries
from app.services.retrieval_trace import RetrievalTrace
from app.services.retriever import RetrievedChunk, retrieve_chunks


DEFAULT_FIXTURE = Path("evaluation/sample_multilayer_reasoning.json")
DEFAULT_OUTPUT_DIR = Path("benchmark_results/reasoning")


def _resolve_document(fixture_path: Path, document: ReasoningDocument) -> Path:
    """픽스처 기준으로 문서 경로를 해석하고 존재를 확인한다."""
    path = Path(document.path)
    if not path.is_absolute():
        path = fixture_path.parent / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Reasoning evaluation document not found: {path}")
    return path


def _create_corpus(
    db: Session,
    fixture_path: Path,
    documents: list[ReasoningDocument],
) -> tuple[User, list[Document], dict[str, Path]]:
    """평가 전용 사용자와 문서 행을 만들어 코퍼스를 격리한다."""
    user = User(
        username=f"reasoning-benchmark-{uuid.uuid4().hex}",
        password_hash="reasoning-benchmark-account-has-no-login-secret",
        role="user",
    )
    db.add(user)
    db.flush()

    paths = {
        document.title: _resolve_document(fixture_path, document)
        for document in documents
    }
    rows = [
        document_repository.create_document(
            db,
            owner_id=user.id,
            title=document.title,
            file_path=str(paths[document.title]),
            mime_type="application/pdf",
        )
        for document in documents
    ]
    db.commit()
    return user, rows, paths


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


def _chunk_source_keys(chunks: list[RetrievedChunk]) -> set[tuple[str, int]]:
    """검색 청크가 포괄하는 문서·페이지 키를 펼친다."""
    return {
        (chunk.document_title, page)
        for chunk in chunks
        if chunk.page_start is not None and chunk.page_end is not None
        for page in range(chunk.page_start, chunk.page_end + 1)
    }


def _source_recall(case: ReasoningCase, chunks: list[RetrievedChunk]) -> float:
    """사례의 정답 출처 중 검색된 비율을 계산한다."""
    expected = {(source.document, source.page) for source in case.relevant_sources}
    retrieved = _chunk_source_keys(chunks)
    return len(expected & retrieved) / len(expected)


def _citation_metrics(case: ReasoningCase, sources: list[Any]) -> dict[str, Any]:
    """생성 답변의 인용을 정답 출처와 비교한다."""
    expected = {(source.document, source.page) for source in case.relevant_sources}
    cited = {
        (source.document_title, source.page)
        for source in sources
        if source.page is not None
    }
    if not cited:
        return {
            "status": "not_applicable" if case.expected_behavior == "abstain" else "missing",
            "expected_source_precision": None,
            "expected_source_recall": 0.0,
            "unexpected_sources": [],
        }
    matching = cited & expected
    precision = len(matching) / len(cited)
    recall = len(matching) / len(expected)
    return {
        "status": "aligned" if precision == 1.0 else "review",
        "expected_source_precision": precision,
        "expected_source_recall": recall,
        "unexpected_sources": [
            {"document": document, "page": page}
            for document, page in sorted(cited - expected)
        ],
    }


def _facet_recall(case: ReasoningCase, chunks: list[RetrievedChunk]) -> dict[str, bool]:
    """각 근거 단위가 검색 결과에 포함됐는지 표시한다."""
    retrieved = _chunk_source_keys(chunks)
    return {
        facet.facet_id: any(
            (source.document, source.page) in retrieved
            for source in facet.relevant_sources
        )
        for facet in case.evidence_facets
    }


def _relevant_page_audit(
    db: Session,
    owner_id: int,
    case: ReasoningCase,
) -> list[dict[str, Any]]:
    """정답 페이지의 추출 텍스트와 시각 처리 상태를 수집한다."""
    requested = {(source.document, source.page) for source in case.relevant_sources}
    rows = db.execute(
        select(
            Document.title,
            DocumentPage.page_number,
            DocumentPage.text,
            DocumentPage.page_metadata,
        )
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.owner_id == owner_id)
    )
    audit = []
    for title, page_number, text, page_metadata in rows:
        if (title, page_number) not in requested:
            continue
        caption = (page_metadata or {}).get("vision_caption") or {}
        audit.append(
            {
                "document": title,
                "page": page_number,
                "text_chars": len(text or ""),
                "text_preview": " ".join((text or "").split())[:240],
                "visual_dependency": (page_metadata or {}).get("visual_dependency"),
                "vision_caption": {
                    key: caption[key]
                    for key in ("status", "version", "model", "confidence", "error_type")
                    if key in caption
                },
            }
        )
    return audit


def _automatic_gate(
    expected_behavior: str,
    outcome_status: str,
    answer: str = "",
) -> str:
    """예상 답변 행동과 실제 결과로 자동 판정 상태를 정한다."""
    if expected_behavior == "grounded_answer":
        return "review" if outcome_status == "grounded" else "fail"
    if expected_behavior == "qualified_answer":
        return "review" if outcome_status == "grounded" else "fail"
    accepted_abstentions = {
        EMPTY_CONTEXT_ANSWER,
        INSUFFICIENT_EVIDENCE_ANSWER,
        VISUAL_EVIDENCE_LIMIT_ANSWER,
    }
    return (
        "pass"
        if outcome_status in {"no_context", "no_source"} or answer in accepted_abstentions
        else "fail"
    )

def _failure_reason(
    case: ReasoningCase,
    *,
    final_source_recall: float,
    outcome_status: str,
    citation_accuracy: dict[str, Any],
    answer: str = "",
) -> str | None:
    """검색·추론·인용 단계 중 실패 원인을 우선순위로 분류한다."""
    if (
        case.expected_behavior == "abstain"
        and _automatic_gate(case.expected_behavior, outcome_status, answer) == "pass"
    ):
        return None
    if final_source_recall < 1.0:
        return "retrieval_gap"
    if case.expected_behavior == "abstain" and outcome_status == "grounded":
        return "grounding_gap"
    if case.expected_behavior != "abstain" and outcome_status != "grounded":
        return "reasoning_gap"
    if citation_accuracy["status"] in {"fail", "missing"}:
        return "citation_gap"
    return None


def _evaluate_case(
    db: Session,
    owner_id: int,
    case: ReasoningCase,
    top_k: int,
    *,
    iteration: int,
    corpus_mode: str,
) -> dict[str, Any]:
    """검색부터 답변 생성까지 한 사례를 실행하고 추적 정보를 남긴다."""
    started = time.perf_counter()
    trace = RetrievalTrace(
        request_id=f"reasoning-{corpus_mode}-{case.case_id}-{iteration}-{uuid.uuid4().hex[:8]}"
    )
    try:
        plan = plan_retrieval_queries(case.question, [])
        goals = plan.goals
        trace.set_query_plan(plan.standalone_query, goals)
        initial_chunks = retrieve_chunks(
            db,
            owner_id=owner_id,
            question=plan.standalone_query,
            top_k=top_k,
            goals=goals,
            trace=trace,
            trace_stage="initial",
        )
        final_chunks = complete_evidence_coverage(
            db=db,
            owner_id=owner_id,
            question=case.question,
            goals=goals,
            chunks=initial_chunks,
            trace=trace,
        )
        evidence_matrix = build_evidence_matrix(goals, trace)
        generated = generate_answer(
            case.question,
            final_chunks,
            evidence_matrix=evidence_matrix,
        )
        trace_payload = trace.complete(
            answer=generated.answer,
            chunks=final_chunks,
            sources=generated.sources,
        )
        outcome_status = trace_payload["outcome"]["status"]
        initial_source_recall = _source_recall(case, initial_chunks)
        final_source_recall = _source_recall(case, final_chunks)
        initial_facet_recall = _facet_recall(case, initial_chunks)
        final_facet_recall = _facet_recall(case, final_chunks)
        citation_accuracy = _citation_metrics(case, generated.sources)
        return {
            "case_id": case.case_id,
            "iteration": iteration,
            "corpus_mode": corpus_mode,
            "group": case.group,
            "question": case.question,
            "reasoning_depth": case.reasoning_depth,
            "answerability": case.answerability,
            "expected_behavior": case.expected_behavior,
            "evidence_modality": case.evidence_modality,
            "reference_queries": case.reference_queries,
            "required_answer_claims": case.required_answer_claims,
            "required_limitations": case.required_limitations,
            "notes": case.notes,
            "answer": generated.answer,
            "sources": [source.model_dump() for source in generated.sources],
            "initial_source_recall": initial_source_recall,
            "final_source_recall": final_source_recall,
            "initial_facet_recall": initial_facet_recall,
            "final_facet_recall": final_facet_recall,
            "relevant_page_audit": _relevant_page_audit(db, owner_id, case),
            "search_success": final_source_recall == 1.0
            and all(final_facet_recall.values()),
            "citation_accuracy": citation_accuracy,
            "failure_reason": _failure_reason(
                case,
                final_source_recall=final_source_recall,
                outcome_status=outcome_status,
                citation_accuracy=citation_accuracy,
                answer=generated.answer,
            ),
            "automatic_gate": _automatic_gate(
                case.expected_behavior,
                outcome_status,
                generated.answer,
            ),
            "manual_review": {
                "classification": None,
                "claim_correctness": None,
                "completeness": None,
                "grounding": None,
                "limitation_calibration": None,
                "notes": "",
            },
            "trace": trace_payload,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        return {
            "case_id": case.case_id,
            "iteration": iteration,
            "corpus_mode": corpus_mode,
            "group": case.group,
            "question": case.question,
            "expected_behavior": case.expected_behavior,
            "automatic_gate": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "trace": trace.to_dict(),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def _selected_groups(
    fixture: ReasoningEvaluationFixture,
    requested: list[str] | None,
) -> list[str]:
    """요청한 문서 그룹을 검증하고 픽스처 순서로 선택한다."""
    available = list(dict.fromkeys(document.group for document in fixture.documents))
    if not requested:
        return available
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"Unknown reasoning groups: {', '.join(unknown)}")
    return list(dict.fromkeys(requested))


def run_benchmark(
    fixture_path: Path,
    *,
    groups: list[str] | None = None,
    case_ids: list[str] | None = None,
    preset_key: str = "balanced",
    algorithm_key: str = "hybrid",
    iterations: int = 1,
    corpus_mode: str = "isolated",
) -> dict[str, Any]:
    """격리 코퍼스에서 추론 평가를 실행하고 설정과 데이터를 원복한다."""
    fixture_path = fixture_path.resolve()
    fixture = load_reasoning_fixture(fixture_path)
    selected_groups = _selected_groups(fixture, groups)
    known_case_ids = {case.case_id for case in fixture.cases}
    if case_ids:
        unknown_cases = sorted(set(case_ids) - known_case_ids)
        if unknown_cases:
            raise ValueError(f"Unknown reasoning cases: {', '.join(unknown_cases)}")
    if not 1 <= iterations <= 10:
        raise ValueError("Iterations must be between 1 and 10")
    if corpus_mode not in {"isolated", "combined"}:
        raise ValueError("Corpus mode must be isolated or combined")

    preset_keys = {preset.key for preset in BUILT_IN_PRESETS}
    if preset_key not in preset_keys:
        raise ValueError(f"Unknown preset: {preset_key}")
    if algorithm_key not in {algorithm.value for algorithm in SearchAlgorithmKey}:
        raise ValueError(f"Unknown algorithm: {algorithm_key}")

    selected_cases = [
        case
        for case in fixture.cases
        if case.group in selected_groups and (not case_ids or case.case_id in case_ids)
    ]
    # 통합 모드는 문서 간 방해 요소를 드러내고, 격리 모드는 그룹별 원인을 좁힌다.
    started_at = datetime.now(UTC)
    db = SessionLocal()
    configuration = retrieval_config_repository.get_configuration(db)
    original_configuration = (
        configuration.active_preset_key,
        configuration.active_search_algorithm_key,
        configuration.index_version,
    )
    group_results: list[dict[str, Any]] = []

    def evaluate_cases(owner_id: int, cases: list[ReasoningCase], top_k: int) -> list[dict[str, Any]]:
        """선택한 사례를 지정 횟수만큼 평가한다."""
        return [
            _evaluate_case(
                db,
                owner_id,
                case,
                top_k,
                iteration=iteration,
                corpus_mode=corpus_mode,
            )
            for case in cases
            for iteration in range(1, iterations + 1)
        ]

    def document_report(
        documents: list[ReasoningDocument],
        paths: dict[str, Path],
    ) -> list[dict[str, str]]:
        """평가 문서 경로와 내용 해시를 보고서에 기록한다."""
        return [
            {
                "title": document.title,
                "path": str(paths[document.title]),
                "sha256": hashlib.sha256(paths[document.title].read_bytes()).hexdigest(),
            }
            for document in documents
        ]

    def index_documents(
        documents: list[Document],
        *,
        target_index_version: int,
    ) -> None:
        """임시 문서를 지정 인덱스 버전으로 처리한다."""
        for document in documents:
            if not process_document(
                document.id,
                preset_key=preset_key,
                index_version=target_index_version,
            ):
                raise RuntimeError(f"Reasoning document indexing failed: {document.title}")

    # 임시 사용자를 써야 삭제와 소유권 검사가 운영 경로와 같아진다.
    try:
        preset = retrieval_config_repository.get_preset(db, preset_key)
        if preset is None:
            raise RuntimeError(f"Preset is missing from database: {preset_key}")
        configuration.active_preset_key = preset_key
        configuration.active_search_algorithm_key = algorithm_key
        db.commit()

        if corpus_mode == "combined":
            user: User | None = None
            indexing_started = time.perf_counter()
            try:
                documents = fixture.documents
                user, corpus_documents, paths = _create_corpus(db, fixture_path, documents)
                index_documents(
                    corpus_documents,
                    target_index_version=original_configuration[2] + 1,
                )
                indexing_ms = round((time.perf_counter() - indexing_started) * 1000, 2)
                documents_payload = document_report(documents, paths)
                for group in selected_groups:
                    cases = [case for case in selected_cases if case.group == group]
                    if cases:
                        group_results.append(
                            {
                                "group": group,
                                "corpus_mode": corpus_mode,
                                "document_count": len(documents),
                                "indexing_ms": indexing_ms,
                                "documents": documents_payload,
                                "cases": evaluate_cases(user.id, cases, preset.top_k),
                            }
                        )
            finally:
                if user is not None:
                    _delete_corpus(db, user.id)
        else:
            for group_index, group in enumerate(selected_groups, start=1):
                documents = [
                    document for document in fixture.documents if document.group == group
                ]
                cases = [case for case in selected_cases if case.group == group]
                if not cases:
                    continue

                user = None
                indexing_started = time.perf_counter()
                try:
                    user, corpus_documents, paths = _create_corpus(
                        db,
                        fixture_path,
                        documents,
                    )
                    index_documents(
                        corpus_documents,
                        target_index_version=original_configuration[2] + group_index,
                    )
                    group_results.append(
                        {
                            "group": group,
                            "corpus_mode": corpus_mode,
                            "document_count": len(documents),
                            "indexing_ms": round(
                                (time.perf_counter() - indexing_started) * 1000,
                                2,
                            ),
                            "documents": document_report(documents, paths),
                            "cases": evaluate_cases(user.id, cases, preset.top_k),
                        }
                    )
                finally:
                    if user is not None:
                        _delete_corpus(db, user.id)
    finally:
        try:
            configuration = retrieval_config_repository.get_configuration(db)
            configuration.active_preset_key = original_configuration[0]
            configuration.active_search_algorithm_key = original_configuration[1]
            configuration.index_version = original_configuration[2]
            db.commit()
        finally:
            db.close()

    completed_at = datetime.now(UTC)
    return {
        "schema_version": 2,
        "fixture": {
            "name": fixture.name,
            "path": str(fixture_path),
            "sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        },
        "run": {
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": (completed_at - started_at).total_seconds(),
            "preset": preset_key,
            "algorithm": algorithm_key,
            "groups": selected_groups,
            "iterations": iterations,
            "corpus_mode": corpus_mode,
        },
        "groups": group_results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """추론 평가 결과를 수동 검토용 마크다운으로 렌더링한다."""
    lines = [
        f"# Reasoning Benchmark: {report['fixture']['name']}",
        "",
        f"- Completed: `{report['run']['completed_at']}`",
        f"- Preset / algorithm: `{report['run']['preset']} / {report['run']['algorithm']}`",
        f"- Duration: `{report['run']['duration_seconds']:.2f}s`",
        f"- Corpus mode / iterations: `{report['run']['corpus_mode']} / {report['run']['iterations']}`",
        "- Automatic gates do not replace manual semantic review.",
        "",
        "| Group | Case | Run | Capability | Search | Final recall | Citation | Outcome | Gate |",
        "|---|---|---:|---|---|---:|---|---|---|",
    ]
    for group in report["groups"]:
        for case in group["cases"]:
            trace = case.get("trace", {})
            outcome = trace.get("outcome", {}).get("status", "error")
            lines.append(
                f"| {group['group']} | {case['case_id']} | {case.get('iteration', 1)} | "
                f"{case.get('answerability', '-')} | "
                f"{'pass' if case.get('search_success') else 'fail'} | "
                f"{case.get('final_source_recall', 0):.3f} | "
                f"{case.get('citation_accuracy', {}).get('status', 'error')} | "
                f"{outcome} | {case['automatic_gate']} |"
            )

    for group in report["groups"]:
        lines.extend(["", f"## {group['group']}", ""])
        for case in group["cases"]:
            lines.extend(
                [
                    f"### {case['case_id']} · run {case.get('iteration', 1)}",
                    "",
                    f"- Expected: `{case['expected_behavior']}`",
                    f"- Automatic gate: `{case['automatic_gate']}`",
                    f"- Question: {case['question']}",
                ]
            )
            if "error" in case:
                lines.extend([f"- Error: `{case['error']}`", ""])
                continue
            lines.extend(
                [
                    f"- Initial/final source recall: "
                    f"`{case['initial_source_recall']:.3f} / {case['final_source_recall']:.3f}`",
                    f"- Search success: `{case['search_success']}`",
                    f"- Citation accuracy: `{case['citation_accuracy']}`",
                    f"- Failure reason: `{case['failure_reason']}`",
                    f"- Planned queries: `{case['trace']['query_plan'].get('queries', [])}`",
                    f"- Required claims: `{case['required_answer_claims']}`",
                    f"- Required limitations: `{case['required_limitations']}`",
                    "",
                    "**Answer**",
                    "",
                    *[f"> {line}" for line in case["answer"].splitlines()],
                    "",
                    f"Sources: `{case['sources']}`",
                    "",
                    "Manual classification: `pass / partial / fail` (select one)",
                    "",
                ]
            )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    """추론 벤치마크 명령행 옵션을 해석한다."""
    parser = argparse.ArgumentParser(
        description="Evaluate multi-layer reasoning over real PDF groups"
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--group", action="append", dest="groups")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--preset", default="balanced")
    parser.add_argument("--algorithm", default="hybrid")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument(
        "--corpus-mode",
        choices=("isolated", "combined"),
        default="isolated",
    )
    return parser.parse_args()


def main() -> int:
    """추론 벤치마크를 실행해 JSON과 검토용 보고서를 저장한다."""
    args = _parse_args()
    report = run_benchmark(
        args.fixture,
        groups=args.groups,
        case_ids=args.case_ids,
        preset_key=args.preset,
        algorithm_key=args.algorithm,
        iterations=args.iterations,
        corpus_mode=args.corpus_mode,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base_path = args.output_dir / f"reasoning-benchmark-{timestamp}"
    json_path = base_path.with_suffix(".json")
    markdown_path = base_path.with_suffix(".md")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(markdown_path.read_text(encoding="utf-8"))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
