from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReasoningDocument(BaseModel):
    """추론 평가 문서를 격리할 그룹과 경로로 지정한다."""
    group: str = Field(min_length=1)
    path: str = Field(min_length=1)
    title: str = Field(min_length=1)


class ReasoningSource(BaseModel):
    """추론 정답의 근거 문서와 페이지를 가리킨다."""
    document: str = Field(min_length=1)
    page: int = Field(ge=1)


class ReasoningEvidenceFacet(BaseModel):
    """추론 단계 하나를 뒷받침하는 정답 출처 묶음이다."""
    facet_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(min_length=1)
    relevant_sources: list[ReasoningSource] = Field(min_length=1)


class ReasoningCase(BaseModel):
    """질문별 추론 깊이와 답변·근거 계약을 정의한다."""
    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    group: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reasoning_depth: int = Field(ge=1, le=4)
    answerability: Literal["full", "partial", "none"]
    expected_behavior: Literal["grounded_answer", "qualified_answer", "abstain"]
    evidence_modality: Literal["text", "mixed", "visual_only"]
    reference_queries: list[str] = Field(min_length=1, max_length=4)
    relevant_sources: list[ReasoningSource] = Field(min_length=1)
    evidence_facets: list[ReasoningEvidenceFacet] = Field(min_length=1)
    required_answer_claims: list[str] = Field(default_factory=list)
    required_limitations: list[str] = Field(default_factory=list)
    notes: str = ""


class ReasoningEvaluationFixture(BaseModel):
    """그룹별 추론 코퍼스와 사례 참조의 무결성을 보장한다."""
    schema_version: Literal[1]
    name: str = Field(min_length=1)
    description: str = ""
    documents: list[ReasoningDocument] = Field(min_length=1)
    cases: list[ReasoningCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "ReasoningEvaluationFixture":
        """사례의 답변 요구와 그룹별 정답 출처가 일치하는지 확인한다."""
        document_titles = [document.title for document in self.documents]
        if len(document_titles) != len(set(document_titles)):
            raise ValueError("Reasoning document titles must be unique")

        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Reasoning case IDs must be unique")

        documents_by_title = {document.title: document for document in self.documents}
        for case in self.cases:
            if case.expected_behavior == "grounded_answer" and not case.required_answer_claims:
                raise ValueError(
                    f"Grounded answer cases require answer claims: {case.case_id}"
                )
            if case.expected_behavior == "qualified_answer" and not case.required_limitations:
                raise ValueError(
                    f"Qualified answer cases require limitations: {case.case_id}"
                )

            facet_ids = [facet.facet_id for facet in case.evidence_facets]
            if len(facet_ids) != len(set(facet_ids)):
                raise ValueError(f"Evidence facet IDs must be unique: {case.case_id}")

            case_sources = {
                (source.document, source.page) for source in case.relevant_sources
            }
            facet_sources = {
                (source.document, source.page)
                for facet in case.evidence_facets
                for source in facet.relevant_sources
            }
            if facet_sources != case_sources:
                raise ValueError(
                    f"Evidence facet sources must match relevant sources: {case.case_id}"
                )

            for document_title, _ in case_sources:
                document = documents_by_title.get(document_title)
                if document is None:
                    raise ValueError(
                        f"Unknown document in case {case.case_id}: {document_title}"
                    )
                if document.group != case.group:
                    raise ValueError(
                        f"Cross-group source in case {case.case_id}: {document_title}"
                    )
        return self


def load_reasoning_fixture(path: Path) -> ReasoningEvaluationFixture:
    """JSON 추론 픽스처를 읽고 평가 계약을 검증한다."""
    return ReasoningEvaluationFixture.model_validate_json(
        path.read_text(encoding="utf-8")
    )
