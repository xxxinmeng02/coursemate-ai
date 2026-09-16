from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import storage
from app.models.chunk import Chunk
from app.models.content import Content

TARGET_CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
BOUNDARY_WINDOW = 200


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

    Chunk page numbers are 1-based, matching user-facing PDF metadata. Chunks
    are indexed globally for the Content, while each page is chunked separately.
    """
    try:
        content.status = "processing"
        db.execute(delete(Chunk).where(Chunk.content_id == content.id))
        db.commit()

        pdf_path = storage.storage_path_for_hash(content.content_hash)
        extracted_pages = extract_pdf_pages(pdf_path)
        normalized_pages = [normalize_text(page) for page in extracted_pages]
        if not _has_meaningful_text(normalized_pages):
            raise ContentProcessingError("PDF contains no meaningful extracted text")

        chunks: list[Chunk] = []
        chunk_index = 0
        for page_number, page_text in enumerate(normalized_pages, start=1):
            for chunk_text in chunk_page(page_text):
                chunks.append(
                    Chunk(
                        content_id=content.id,
                        text=chunk_text,
                        page_number=page_number,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

        db.add_all(chunks)
        content.status = "ready"
        db.commit()
        return chunks
    except Exception as exc:
        db.rollback()
        try:
            db.execute(delete(Chunk).where(Chunk.content_id == content.id))
            content.status = "failed"
            db.commit()
        except Exception as cleanup_exc:
            db.rollback()
            raise ContentProcessingError(
                "Could not clean up failed content processing"
            ) from cleanup_exc

        if isinstance(exc, ContentProcessingError):
            raise
        raise ContentProcessingError("Could not process content") from exc
