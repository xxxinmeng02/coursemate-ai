"""Course retrieval: query embedding followed by an exact scoped vector query."""
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app import embeddings
from app.models.chunk import Chunk
from app.models.content import Content
from app.models.course import Course
from app.models.document import Document

MAX_TOP_K = 50
MAX_QUERY_CHARS = 2000


class CourseNotFoundError(LookupError):
    """The requested Course does not exist."""


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: int
    text: str
    page_number: int | None
    document_id: int
    document_name: str
    score: float


def normalize_search_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters")
    return query


def _course_chunks(db: Session, course_id: int, config_id: str) -> Select:
    # One representative document per Content, chosen ONLY inside this Course.
    documents = (
        select(Document.content_id, func.min(Document.id).label("document_id"))
        .where(Document.course_id == course_id)
        .group_by(Document.content_id).subquery()
    )
    candidates = (
        select(Chunk.id.label("chunk_id"), Chunk.text, Chunk.page_number,
               Document.id.label("document_id"), Document.name.label("document_name"))
        .join(Content, Content.id == Chunk.content_id)
        .join(documents, documents.c.content_id == Content.id)
        .join(Document, Document.id == documents.c.document_id)
        .where(Content.status == "ready", Chunk.embedding.is_not(None),
               Chunk.embedding_config == config_id)
    )
    if db.get_bind().dialect.name == "postgresql":
        # Cosine distance is undefined for a zero vector. The SQLite variant is
        # only for negative controls (missing Course/empty candidates), not SQL ranking.
        candidates = candidates.where(func.vector_norm(Chunk.embedding) > 0)
    return candidates


def _search_course_vectors(
    db: Session, candidates: Select, vector: list[float], top_k: int,
) -> list[RetrievalResult]:
    distance = Chunk.embedding.cosine_distance(vector)
    statement = candidates.add_columns((1.0 - distance).label("score")) \
        .order_by(distance.asc(), Chunk.id.asc()).limit(top_k)
    return [RetrievalResult(**row) for row in db.execute(statement).mappings()]


def search_course(
    db: Session, course_id: int, query: str, top_k: int,
) -> list[RetrievalResult]:
    """Read using the caller's Session; never commit, close, or mutate it."""
    query = normalize_search_query(query)
    if type(top_k) is not int or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be an integer between 1 and {MAX_TOP_K}")
    with db.no_autoflush:
        if db.get(Course, course_id) is None:
            raise CourseNotFoundError("Course not found")
        config = embeddings.get_embedding_config()
        candidates = _course_chunks(db, course_id, config.identifier)
        if not db.scalar(select(candidates.exists())):
            return []
        vector = embeddings.validate_embedding(embeddings.embed_text(query, config=config))
        return _search_course_vectors(db, candidates, vector, top_k)
