from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class CourseCreate(BaseModel):
    """Payload for creating a course."""

    name: str

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty or whitespace only")
        return stripped


class CourseSummary(BaseModel):
    """Basic course information returned by list/create endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class DocumentSummary(BaseModel):
    """Document summary inside a course detail response."""

    id: int
    name: str
    created_at: datetime
    status: str


class CourseDetail(BaseModel):
    """Course information plus its documents and their processing status."""

    id: int
    name: str
    created_at: datetime
    documents: list[DocumentSummary]
