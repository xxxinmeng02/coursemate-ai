"""Provider-backed sanity and course evaluation in isolated PostgreSQL schemas.

The geometry directions in the fixture are consumed only by deterministic
tests. This command always uses the configured real embedding provider.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
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
from app.parsing import CHUNK_OVERLAP, TARGET_CHUNK_SIZE, chunk_page, normalize_text
from app.retrieval import MAX_TOP_K, RetrievalResult, search_course

TOPICS_PATH = Path(__file__).resolve().parents[3] / "evals/retrieval/topics.json"
BENCHMARK_PATH = TOPICS_PATH.with_name("parallel_computing.json")


def benchmark_chunks(fixture: dict) -> list[dict]:
    """Use the existing page-local chunker; verify golden evidence before API use."""
    names = [document["name"] for document in fixture["documents"]]
    questions = fixture["questions"]
    ids = [case["id"] for case in questions]
    if len(set(names)) != len(names) or not questions or len(set(ids)) != len(ids):
        raise ValueError("Documents and question IDs must be unique; questions must not be empty")
    chunks = []
    for document in fixture["documents"]:
        index = 0
        for page, value in enumerate(document["pages"], 1):
            for passage in chunk_page(normalize_text(value)):
                chunks.append({"document_name": document["name"], "page_number": page,
                               "chunk_index": index, "text": passage})
                index += 1
    # Search the entire corpus once, allowing uncensored MRR and Top 1/3/5 prefixes.
    if not 5 < len(chunks) <= MAX_TOP_K:
        raise ValueError(f"Benchmark must contain 6–{MAX_TOP_K} chunks")
    for case in questions:
        candidates = [c for c in chunks if c["document_name"] == case["expected_document"]
                      and c["page_number"] == case["expected_page"]]
        alternatives = case.get("alternative_evidence", [])
        if not isinstance(alternatives, list):
            raise ValueError("Alternative evidence must be a list of spans")
        spans = [case["evidence"], *alternatives]
        if not case["question"].strip() or any(
            not isinstance(span, str) or not span.strip()
            or not any(span in c["text"] for c in candidates) for span in spans
        ):
            raise ValueError(f"Golden evidence does not resolve to a chunk: {case['id']}")
    return chunks


def _matches_evidence(case: dict, chunk: dict) -> bool:
    return (chunk["document_name"] == case["expected_document"]
            and chunk["page_number"] == case["expected_page"]
            and any(span in chunk["text"]
                    for span in [case["evidence"], *case.get("alternative_evidence", [])]))


def grade_question(
    case: dict, hits: list[RetrievalResult], expected_ids: set[int], latency_ms: float,
) -> dict:
    ranked = [{**asdict(hit), "rank": i, "relevant": hit.chunk_id in expected_ids}
              for i, hit in enumerate(hits, 1)]
    relevant = [hit for hit in ranked if hit["relevant"]]
    rank = relevant[0]["rank"] if relevant else None
    return {**case, "expected_chunk_ids": sorted(expected_ids),
            "first_relevant_rank": rank, "latency_ms": latency_ms,
            "outcome": "top_1" if rank == 1 else "weak_top_5" if rank and rank <= 5 else "miss_at_5",
            "top_5": ranked[:5], "expected_hits": relevant,
            "ranked_chunk_ids": [hit.chunk_id for hit in hits]}


def summarize_benchmark(rows: list[dict]) -> dict:
    """One golden evidence unit per question; overlapping chunks are alternatives."""
    if not rows:
        raise ValueError("Cannot summarize an empty evaluation")
    ranks = [row["first_relevant_rank"] for row in rows]
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "metrics": {**{f"recall_at_{k}": sum(rank is not None and rank <= k for rank in ranks) / len(rows)
                       for k in (1, 3, 5)},
                    "mrr": sum(1 / rank if rank else 0 for rank in ranks) / len(rows)},
        "latency_ms": {"mean": statistics.mean(latencies), "median": statistics.median(latencies),
                       "p95": latencies[math.ceil(0.95 * len(latencies)) - 1]},
    }


def benchmark_metadata(
    fixture: dict, chunks: list[dict], config: embeddings.EmbeddingConfig | None,
) -> dict:
    return {"dataset_id": fixture["id"], "dataset_sha256": hashlib.sha256(
                json.dumps(fixture, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "dataset_provenance": fixture["provenance"], "question_count": len(fixture["questions"]),
            "document_count": len(fixture["documents"]), "chunk_count": len(chunks),
            "embedding_config": config.identifier if config else None,
            "chunking": {"target_characters": TARGET_CHUNK_SIZE, "overlap_characters": CHUNK_OVERLAP},
            "latency_scope": "One full-course search including query embedding/network and SQL; excludes backfill",
            "run_at_utc": datetime.now(timezone.utc).isoformat()}


def _seed_benchmark(factory: sessionmaker, fixture: dict, chunks: list[dict]) -> tuple[int, list[dict], list[int]]:
    """Only the caller's isolated evaluation schema is populated."""
    with factory() as db:
        course = Course(name=fixture["course"])
        db.add(course)
        db.flush()
        contents, manifest = [], []
        for document in fixture["documents"]:
            content = Content(content_hash=uuid.uuid4().hex * 2, storage_key="evaluation/unused.txt",
                              file_type="text/plain", status="ready")
            db.add(content)
            db.flush()
            doc = Document(course_id=course.id, content_id=content.id, name=document["name"])
            db.add(doc)
            db.flush()
            for item in chunks:
                if item["document_name"] == doc.name:
                    chunk = Chunk(content_id=content.id, text=item["text"],
                                  page_number=item["page_number"], chunk_index=item["chunk_index"])
                    db.add(chunk)
                    db.flush()
                    manifest.append({**item, "chunk_id": chunk.id, "document_id": doc.id})
            contents.append(content.id)
        course_id = course.id
        db.commit()
    return course_id, manifest, contents


def evaluate_benchmark(factory: sessionmaker, fixture: dict) -> dict:
    chunks = benchmark_chunks(fixture)
    config = embeddings.get_embedding_config()
    metadata = benchmark_metadata(fixture, chunks, config)
    course_id, manifest, contents = _seed_benchmark(factory, fixture, chunks)
    for content_id in contents:
        with factory() as db:
            embed_content(db, content_id, config=config)
    rows = []
    for case in fixture["questions"]:
        if embeddings.get_embedding_config() != config:
            raise embeddings.EmbeddingError("Embedding configuration changed during evaluation")
        with factory() as db:
            started = time.perf_counter()
            hits = search_course(db, course_id, case["question"], len(chunks))
            elapsed = (time.perf_counter() - started) * 1000
        if len(hits) != len(chunks) or any(not math.isfinite(hit.score) for hit in hits):
            raise ValueError("Evaluation did not retrieve the complete eligible corpus")
        expected = {chunk["chunk_id"] for chunk in manifest if _matches_evidence(case, chunk)}
        rows.append(grade_question(case, hits, expected, elapsed))
    return {**metadata, **summarize_benchmark(rows), "status": "completed",
            "real_embeddings_used": True, "chunk_manifest": manifest, "results": rows}


@contextmanager
def evaluation_database(url: str):
    """Share schema lifecycle between the original sanity check and benchmark."""
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise ValueError("TEST_POSTGRES_URL must use PostgreSQL")
    schema = f"retrieval_eval_{uuid.uuid4().hex}"
    created = False
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        scoped = engine.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(scoped)
        yield sessionmaker(bind=scoped, autoflush=False, expire_on_commit=False)
    finally:
        try:
            if created:
                with engine.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            engine.dispose()


def _write_record(record: dict, output: Path | None) -> None:
    value = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(value)
    print(value, end="")


def run_benchmark(output: Path | None) -> int:
    fixture = json.loads(BENCHMARK_PATH.read_text())
    chunks = benchmark_chunks(fixture)
    try:
        config = embeddings.get_embedding_config()
    except embeddings.EmbeddingError:
        config = None
    metadata = benchmark_metadata(fixture, chunks, config)
    blocked = {**metadata, "status": "blocked", "real_embeddings_used": False,
               "metrics": {"recall_at_1": None, "recall_at_3": None, "recall_at_5": None, "mrr": None},
               "latency_ms": None, "results": []}
    url = os.getenv("TEST_POSTGRES_URL")
    blocker = ("Invalid embedding configuration" if config is None
               else "OPENAI_API_KEY is not configured" if not os.getenv("OPENAI_API_KEY", "").strip()
               else "Set TEST_POSTGRES_URL to a separate PostgreSQL database" if not url else None)
    if blocker:
        _write_record({**blocked, "blocker": blocker}, output)
        return 2
    try:
        with evaluation_database(url) as factory:
            record = evaluate_benchmark(factory, fixture)
    except (embeddings.EmbeddingError, EmbeddingGenerationError, SQLAlchemyError, ValueError):
        # Calls may already have succeeded before a later failure. Unknown is
        # different from the preflight's proven absence of embedding API calls.
        _write_record({**blocked, "real_embeddings_used": None,
                       "blocker": "Evaluation could not complete; check provider, database and configuration"}, output)
        return 1
    _write_record(record, output)
    return 0


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
    parser = argparse.ArgumentParser(description="Evaluate retrieval using real embeddings")
    parser.add_argument("--benchmark", action="store_true", help="Run the 25-question course benchmark")
    parser.add_argument("--output", type=Path, help="Write the JSON evidence artifact")
    args = parser.parse_args(argv)
    if args.benchmark:
        return run_benchmark(args.output)
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        print("Set TEST_POSTGRES_URL to use an isolated evaluation database", file=sys.stderr)
        return 2
    try:
        with evaluation_database(url) as factory:
            fixture = json.loads(TOPICS_PATH.read_text())
            results = evaluate_topics(factory, fixture)
        _write_record({"embedding_config": embeddings.get_embedding_config().identifier,
                       "results": results}, args.output)
        return 0 if all(result["passed"] for result in results) else 1
    except (embeddings.EmbeddingError, EmbeddingGenerationError, SQLAlchemyError, ValueError):
        print("Retrieval evaluation failed; check database and embedding configuration", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
