from __future__ import annotations

import logging
import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete, inspect, update
from sqlalchemy.orm import Session

from app import storage
from app.models.chunk import Chunk
from app.models.content import Content

TARGET_CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
BOUNDARY_WINDOW = 200
logger = logging.getLogger(__name__)


class ContentProcessingError(RuntimeError):
    """Raised when a stored PDF cannot be parsed and persisted."""


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Extract raw text in source order, one string for each PDF page."""
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def normalize_text(text: str) -> str:
    """Normalize line endings and excessive inline whitespace conservatively."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in normalized.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _nearest_boundary(
    text: str,
    target: int,
    start: int,
) -> int:
    """Find a nearby split, preferring paragraph, newline, then whitespace."""
    window_start = max(start + 1, target - BOUNDARY_WINDOW)
    window_end = min(len(text), target + BOUNDARY_WINDOW)
    patterns = (r"\n\s*\n", r"\n", r"[ \t]")

    for pattern in patterns:
        candidates = [
            match.end()
            for match in re.finditer(pattern, text)
            if window_start <= match.end() <= window_end
        ]
        if candidates:
            return min(candidates, key=lambda position: (abs(position - target), position))

    return min(target, len(text))


def chunk_page(
    text: str,
    *,
    target_size: int = TARGET_CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Chunk one normalized page without crossing its boundaries."""
    if target_size <= 0:
        raise ValueError("target_size must be positive")
    if overlap < 0 or overlap >= target_size:
        raise ValueError("overlap must be non-negative and smaller than target_size")
    if not text:
        return []
    if len(text) <= target_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        remaining = len(text) - start
        if remaining <= target_size:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        target = start + target_size
        end = _nearest_boundary(text, target, start)
        if end <= start:
            end = min(target, len(text))

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


def _has_meaningful_text(pages: list[str]) -> bool:
    return any(character.isalnum() for page in pages for character in page)


def process_content(db: Session, content: Content) -> list[Chunk]:
    """Parse one Content's stored PDF and persist its canonical chunk set.

    Use a dedicated, clean session: this function owns commit/rollback. A no-op
    UPDATE locks the current Content row until the outer transaction completes
    (PostgreSQL row lock; SQLite writer lock), refreshing stale ORM state.
    Processing is transaction-local; readers keep seeing the last committed
    status and chunks. A savepoint protects those chunks during replacement.

    Page numbers are 1-based and chunk indexes are global for the Content.
    """
    state = inspect(content)
    if state.session is not db or state.identity is None:
        raise ContentProcessingError("Content must be persisted in the processing session")
    if db.new or db.dirty or db.deleted:
        raise ContentProcessingError("Processing requires a session without pending changes")
    if db.in_nested_transaction():
        raise ContentProcessingError("Processing cannot run inside a caller's savepoint")

    content_id = state.identity[0]
    try:
        # Unlike SELECT FOR UPDATE (ignored by SQLite), this is a write on both
        # supported databases. Do not commit it before extraction/replacement.
        locked_content = db.scalars(
            update(Content)
            .where(Content.id == content_id)
            .values(status=Content.status)
            .returning(Content)
            .execution_options(populate_existing=True, synchronize_session=False)
        ).one_or_none()
        if locked_content is None:
            raise ContentProcessingError("Content no longer exists")
        previous_status = locked_content.status
        if previous_status not in {"uploaded", "failed", "ready"}:
            raise ContentProcessingError(f"Cannot process content in state {previous_status}")

        try:
            with db.begin_nested():
                locked_content.status = "processing"
                db.flush()
                pdf_path = storage.storage_path_for_hash(locked_content.content_hash)
                extracted_pages = extract_pdf_pages(pdf_path)
                normalized_pages = [normalize_text(page) for page in extracted_pages]
                if not _has_meaningful_text(normalized_pages):
                    raise ContentProcessingError("PDF contains no meaningful extracted text")

                chunks: list[Chunk] = []
                for page_number, page_text in enumerate(normalized_pages, start=1):
                    for chunk_text in chunk_page(page_text):
                        chunks.append(
                            Chunk(
                                content_id=content_id,
                                text=chunk_text,
                                page_number=page_number,
                                chunk_index=len(chunks),
                            )
                        )

                db.execute(delete(Chunk).where(Chunk.content_id == content_id))
                db.add_all(chunks)
                locked_content.status = "ready"
                db.flush()
        except Exception as exc:
            # Savepoint rollback restored canonical data; the outer write lock
            # is still held. Never delete chunks as failure cleanup.
            locked_content.status = "ready" if previous_status == "ready" else "failed"
            db.commit()
            logger.exception("PDF processing failed for content_id=%s", content_id)
            if isinstance(exc, ContentProcessingError):
                raise
            raise ContentProcessingError("Could not process content") from exc

        db.commit()
        return chunks
    except ContentProcessingError:
        db.rollback()
        raise
    except Exception as exc:
        # This also covers lock acquisition and final COMMIT failure. Once the
        # lock is released, no separate cleanup/status write may race a worker.
        db.rollback()
        raise ContentProcessingError("Could not persist content processing") from exc
