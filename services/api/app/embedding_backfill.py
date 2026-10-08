"""Retryable embeddings for existing canonical chunks, separate from parsing."""
import argparse
import sys

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import embeddings
from app.database import get_session_factory
from app.models.chunk import Chunk
from app.models.content import Content


class EmbeddingGenerationError(RuntimeError):
    """A Content's embedding transaction could not complete."""


def embed_content(
    db: Session, content_id: int, *, force: bool = False,
    config: embeddings.EmbeddingConfig | None = None,
) -> dict[str, int]:
    """Own commit/rollback in a dedicated clean session, once per Content.

    The Content write lock coordinates with the existing PDF processor. Readers
    see the old committed vectors until the whole embedding update commits.
    Callers must not pass sessions containing other uncommitted business work.
    """
    if db.new or db.dirty or db.deleted or db.in_nested_transaction():
        raise EmbeddingGenerationError("Embedding generation requires a dedicated clean session")
    try:
        config = config or embeddings.get_embedding_config()
        content = db.scalars(
            update(Content).where(Content.id == content_id)
            .values(status=Content.status).returning(Content)
            .execution_options(populate_existing=True, synchronize_session=False)
        ).one_or_none()
        if content is None or content.status != "ready":
            raise EmbeddingGenerationError("Content must exist and be ready")
        chunks = db.scalars(
            select(Chunk).where(Chunk.content_id == content_id).order_by(Chunk.chunk_index)
            .execution_options(populate_existing=True)
        ).all()
        replacements = []
        skipped = 0
        for chunk in chunks:
            if not force and chunk.embedding_config == config.identifier and chunk.embedding is not None:
                try:
                    embeddings.validate_embedding(list(chunk.embedding))
                except embeddings.EmbeddingError:
                    pass  # An invalid existing vector needs repair, not a skip.
                else:
                    skipped += 1
                    continue
            vector = embeddings.validate_embedding(embeddings.embed_text(chunk.text, config=config))
            replacements.append((chunk, vector))
        for chunk, vector in replacements:
            chunk.embedding = vector
            chunk.embedding_config = config.identifier
        db.commit()
        return {"generated": len(replacements), "skipped": skipped}
    except Exception:
        db.rollback()
        raise EmbeddingGenerationError("Could not generate Content embeddings") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed canonical chunks from ready Content")
    parser.add_argument("--content-id", type=int, help="Only process this Content")
    parser.add_argument("--force", action="store_true", help="Replace valid current embeddings too")
    args = parser.parse_args(argv)
    generated = skipped = failed = 0
    try:
        config = embeddings.get_embedding_config()
        factory = get_session_factory()
        if args.content_id is not None:
            ids = [args.content_id]
        else:
            with factory() as db:
                ids = list(db.scalars(select(Content.id).where(Content.status == "ready")
                                      .order_by(Content.id)))
        for content_id in ids:
            with factory() as db:
                try:
                    result = embed_content(db, content_id, force=args.force, config=config)
                except EmbeddingGenerationError:
                    failed += 1
                    print(f"Embedding failed for content_id={content_id}", file=sys.stderr)
                else:
                    generated += result["generated"]
                    skipped += result["skipped"]
    except (RuntimeError, SQLAlchemyError):
        print("Could not initialize embedding backfill", file=sys.stderr)
        return 1
    print(f"generated={generated} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
