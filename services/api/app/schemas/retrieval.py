import os

from pydantic import BaseModel, Field, field_validator

from app.retrieval import MAX_TOP_K, RetrievalResult, normalize_search_query


class RetrievalConfigurationError(RuntimeError):
    """Invalid server-side search defaults, distinct from client validation."""


def get_default_top_k() -> int:
    try:
        value = int(os.getenv("RETRIEVAL_DEFAULT_TOP_K", "5"))
        if not 1 <= value <= MAX_TOP_K:
            raise ValueError
        return value
    except ValueError:
        raise RetrievalConfigurationError("Invalid retrieval default") from None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(
        default=5,
        strict=True, ge=1, le=MAX_TOP_K, validate_default=True,
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return normalize_search_query(value)


class SearchResponse(BaseModel):
    results: list[RetrievalResult]
