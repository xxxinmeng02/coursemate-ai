"""Small provider-backed topic evaluation in an isolated PostgreSQL schema.

The geometry directions in the fixture are consumed only by deterministic
tests. This command always uses the configured real embedding provider.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app import embeddings
from app.database import Base
from app.embedding_backfill import EmbeddingGenerationError, embed_content
from app.models.chunk import Chunk
from app.models.content import Content
from app.models.course import Course
from app.models.document import Document
from app.retrieval import search_course

TOPICS_PATH = Path(__file__).resolve().parents[3] / "evals/retrieval/topics.json"


def evaluate_topics(factory: sessionmaker, fixture: dict) -> list[dict]:
    """Seed only the caller's evaluation schema, reuse backfill and retrieval."""
    config = embeddings.get_embedding_config()
    with factory() as db:
        course = Course(name="Retrieval evaluation")
        db.add(course)
        db.flush()
        course_id = course.id
        topic_by_chunk = {}
        contents = []
        for item in fixture["documents"]:
            content = Content(content_hash=uuid.uuid4().hex * 2,
                              storage_key="evaluation/unused.pdf", file_type="application/pdf",
                              status="ready")
            db.add(content)
            db.flush()
            chunk = Chunk(content_id=content.id, text=item["text"], page_number=1, chunk_index=0)
            db.add(chunk)
            db.add(Document(course_id=course_id, content_id=content.id, name=f"{item['topic']}.pdf"))
            db.flush()
            topic_by_chunk[chunk.id] = item["topic"]
            contents.append(content.id)
        db.commit()
    for content_id in contents:
        with factory() as db:
            embed_content(db, content_id, config=config)
    results = []
    for case in fixture["queries"]:
        with factory() as db:
            ranked = search_course(db, course_id, case["query"], len(topic_by_chunk))
        topics = [topic_by_chunk[hit.chunk_id] for hit in ranked]
        scores = [hit.score for hit in ranked]
        passed = (
            bool(topics) and topics[0] == case["expected_topic"]
            and all(math.isfinite(score) for score in scores)
            and all(scores[0] > score for topic, score in zip(topics[1:], scores[1:])
                    if topic != case["expected_topic"])
        )
        results.append({"query": case["query"], "expected_topic": case["expected_topic"],
                        "actual_topic": topics[0] if topics else None,
                        "ranked_topics": topics, "scores": scores, "passed": passed})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate topic retrieval using real embeddings")
    parser.parse_args(argv)
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        print("Set TEST_POSTGRES_URL to use an isolated evaluation database", file=sys.stderr)
        return 2
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        print("TEST_POSTGRES_URL must use PostgreSQL", file=sys.stderr)
        return 2
    schema = f"retrieval_eval_{uuid.uuid4().hex}"
    created = False
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        scoped = engine.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(scoped)
        factory = sessionmaker(bind=scoped, autoflush=False, expire_on_commit=False)
        fixture = json.loads(TOPICS_PATH.read_text())
        results = evaluate_topics(factory, fixture)
        print(json.dumps({"embedding_config": embeddings.get_embedding_config().identifier,
                          "results": results}, indent=2))
        return 0 if all(result["passed"] for result in results) else 1
    except (embeddings.EmbeddingError, EmbeddingGenerationError, SQLAlchemyError):
        print("Retrieval evaluation failed; check database and embedding configuration", file=sys.stderr)
        return 1
    finally:
        try:
            if created:
                with engine.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
