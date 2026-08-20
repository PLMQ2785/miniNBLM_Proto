from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EvaluationDocument(BaseModel):
    """검색 평가 코퍼스에 포함할 문서를 지정한다."""
    path: str = Field(min_length=1)
    title: str = Field(min_length=1)


class RelevantSource(BaseModel):
    """정답 근거가 있는 문서와 페이지를 가리킨다."""
    document: str = Field(min_length=1)
    page: int = Field(ge=1)


class EvidenceFacet(BaseModel):
    """한 답변 근거를 충족할 수 있는 정답 출처 묶음이다."""
    facet_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(min_length=1)
    relevant_sources: list[RelevantSource] = Field(min_length=1)


class EvaluationCase(BaseModel):
    """질문별 검색 입력과 정답 근거 계약을 정의한다."""
    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    question: str = Field(min_length=1)
    retrieval_queries: list[str] = Field(default_factory=list, max_length=4)
    relevant_sources: list[RelevantSource] = Field(min_length=1)
    evidence_facets: list[EvidenceFacet] = Field(default_factory=list)
    required_answer_claims: list[str] = Field(default_factory=list)


class RetrievalEvaluationFixture(BaseModel):
    """검색 벤치마크가 공유하는 문서와 사례 계약을 검증한다."""
    schema_version: Literal[1, 2]
    name: str = Field(min_length=1)
    description: str = ""
    documents: list[EvaluationDocument] = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "RetrievalEvaluationFixture":
        """픽스처의 식별자와 정답 출처 참조가 일관적인지 확인한다."""
        document_titles = [document.title for document in self.documents]
        if len(document_titles) != len(set(document_titles)):
            raise ValueError("Evaluation document titles must be unique")

        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")

        # 스키마 v2는 근거 단위와 필수 답변 주장을 모두 명시해야 한다.
        if self.schema_version == 2:
            incomplete_cases = [
                case.case_id
                for case in self.cases
                if (
                    not case.retrieval_queries
                    or not case.evidence_facets
                    or not case.required_answer_claims
                )
            ]
            if incomplete_cases:
                raise ValueError(
                    "Schema version 2 cases require retrieval queries, evidence facets, "
                    "and answer claims: "
                    + ", ".join(incomplete_cases)
                )

        for case in self.cases:
            if any(not query.strip() for query in case.retrieval_queries):
                raise ValueError(f"Retrieval queries cannot be blank in case: {case.case_id}")
            facet_ids = [facet.facet_id for facet in case.evidence_facets]
            if len(facet_ids) != len(set(facet_ids)):
                raise ValueError(f"Evidence facet IDs must be unique in case: {case.case_id}")
            facet_sources = {
                (source.document, source.page)
                for facet in case.evidence_facets
                for source in facet.relevant_sources
            }
            case_sources = {
                (source.document, source.page) for source in case.relevant_sources
            }
            # 근거 단위의 정답 집합은 사례 전체 정답 집합과 정확히 같아야 한다.
            if facet_sources and facet_sources != case_sources:
                raise ValueError(
                    f"Evidence facet sources must match relevant sources in case: {case.case_id}"
                )

        known_titles = set(document_titles)
        unknown_titles = {
            source.document
            for case in self.cases
            for source in [
                *case.relevant_sources,
                *(
                    facet_source
                    for facet in case.evidence_facets
                    for facet_source in facet.relevant_sources
                ),
            ]
            if source.document not in known_titles
        }
        if unknown_titles:
            raise ValueError(
                "Relevant sources reference unknown documents: "
                + ", ".join(sorted(unknown_titles))
            )
        return self


def load_evaluation_fixture(path: Path) -> RetrievalEvaluationFixture:
    """JSON 픽스처를 읽고 모든 평가 계약을 검증한다."""
    return RetrievalEvaluationFixture.model_validate_json(path.read_text(encoding="utf-8"))
