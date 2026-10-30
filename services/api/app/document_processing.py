"""Upload-triggered processing: parse a Content, then embed its chunks.

Work runs as a FastAPI background task inside the API process and receives
only a session factory and a Content ID, never a request Session or ORM object.
The in-flight set reflects this process only; after a restart, unfinished
Content reports ``not_indexed`` and can be retried.
"""
import logging
import threading
from typing import Literal

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import embeddings
from app.embedding_backfill import EmbeddingGenerationError, embed_content
from app.models.chunk import Chunk
from app.models.content import Content
from app.parsing import ContentProcessingError, process_content

ProcessingState = Literal["processing", "indexed", "not_indexed", "failed"]
RETRYABLE_STATES = {"not_indexed", "failed"}
logger = logging.getLogger(__name__)

_in_flight: set[int] = set()
_in_flight_lock = threading.Lock()


def claim(content_id: int) -> bool:
    """Reserve a Content for one pipeline run; False if one is already queued."""
    with _in_flight_lock:
        if content_id in _in_flight:
            return False
        _in_flight.add(content_id)
        return True


def _release(content_id: int) -> None:
    with _in_flight_lock:
        _in_flight.discard(content_id)


def run_pipeline(session_factory: sessionmaker[Session], content_id: int) -> None:
    """Parse when needed, then embed. The caller must have claimed content_id."""
    try:
        with session_factory() as db:
            content = db.get(Content, content_id)
            if content is None:
                return
            if content.status in {"uploaded", "failed"}:
                process_content(db, content)
        with session_factory() as db:
            embed_content(db, content_id)
    except (ContentProcessingError, EmbeddingGenerationError) as exc:
        # Both helpers already restored a consistent status; the state is
        # visible to the client as failed or not_indexed.
        logger.warning("Processing stopped for content_id=%s: %s", content_id, exc)
    except Exception:
        logger.exception("Unexpected processing error for content_id=%s", content_id)
    finally:
        _release(content_id)


def processing_states(db: Session, contents: list[Content]) -> dict[int, ProcessingState]:
    """Derive each Content's user-facing state from status and stored vectors."""
    try:
        config_id = embeddings.get_embedding_config().identifier
        current_vector = Chunk.embedding_config == config_id
    except embeddings.EmbeddingError:
        current_vector = false()  # A misconfigured model makes nothing searchable.
    ids = [content.id for content in contents]
    counts = {
        content_id: (total, embedded)
        for content_id, total, embedded in db.execute(
            select(
                Chunk.content_id,
                func.count(Chunk.id),
                func.count(Chunk.id).filter(current_vector),
            )
            .where(Chunk.content_id.in_(ids))
            .group_by(Chunk.content_id)
        )
    } if ids else {}

    with _in_flight_lock:
        in_flight = set(_in_flight)
    states: dict[int, ProcessingState] = {}
    for content in contents:
        total, embedded = counts.get(content.id, (0, 0))
        if content.id in in_flight or content.status == "processing":
            states[content.id] = "processing"
        elif content.status == "failed":
            states[content.id] = "failed"
        elif content.status == "ready" and total and embedded == total:
            states[content.id] = "indexed"
        else:
            states[content.id] = "not_indexed"
    return states
