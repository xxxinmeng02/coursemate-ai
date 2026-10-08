import os

from pydantic import BaseModel, Field, field_validator

from app.retrieval import MAX_TOP_K, RetrievalResult, normalize_search_query


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_DEFAULT_TOP_K", "5")),
        strict=True, ge=1, le=MAX_TOP_K, validate_default=True,
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return normalize_search_query(value)


class SearchResponse(BaseModel):
    results: list[RetrievalResult]
