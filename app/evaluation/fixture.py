from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EvaluationDocument(BaseModel):
    path: str = Field(min_length=1)
    title: str = Field(min_length=1)


class RelevantSource(BaseModel):
    document: str = Field(min_length=1)
    page: int = Field(ge=1)


class EvaluationCase(BaseModel):
    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    question: str = Field(min_length=1)
    relevant_sources: list[RelevantSource] = Field(min_length=1)


class RetrievalEvaluationFixture(BaseModel):
    schema_version: Literal[1]
    name: str = Field(min_length=1)
    description: str = ""
    documents: list[EvaluationDocument] = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "RetrievalEvaluationFixture":
        document_titles = [document.title for document in self.documents]
        if len(document_titles) != len(set(document_titles)):
            raise ValueError("Evaluation document titles must be unique")

        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")

        known_titles = set(document_titles)
        unknown_titles = {
            source.document
            for case in self.cases
            for source in case.relevant_sources
            if source.document not in known_titles
        }
        if unknown_titles:
            raise ValueError(
                "Relevant sources reference unknown documents: "
                + ", ".join(sorted(unknown_titles))
            )
        return self


def load_evaluation_fixture(path: Path) -> RetrievalEvaluationFixture:
    return RetrievalEvaluationFixture.model_validate_json(path.read_text(encoding="utf-8"))
