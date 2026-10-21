"""Parse and embed only the MIT benchmark Course, using the existing pipeline.

Run from the repository root with the API virtualenv, after uploading the five
downloaded PDFs to a dedicated Course:

    services/api/.venv/Scripts/python.exe evals/retrieval/prepare_mit_course.py --course-id 1

The Course must contain exactly the five benchmark PDFs with matching SHA-256.
Uploaded Content is parsed with ``app.parsing.process_content``; ready Content is
then embedded with ``app.embedding_backfill.embed_content``, which sends public
lecture text to the configured embedding provider. ``--parse-only`` skips that.
No other Course or Content is touched.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from sqlalchemy import func, select  # noqa: E402

from app.database import get_session_factory  # noqa: E402
from app.embedding_backfill import EmbeddingGenerationError, embed_content  # noqa: E402
from app.models.chunk import Chunk  # noqa: E402
from app.models.content import Content  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.parsing import process_content  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--parse-only", action="store_true", help="Do not call the embedding provider")
    args = parser.parse_args(argv)

    fixture = json.loads(Path(__file__).with_name("mit_6006.json").read_text(encoding="utf-8"))
    expected = {doc["name"]: doc["sha256"] for doc in fixture["documents"]}
    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(Document.name, Content.id, Content.content_hash)
            .join(Content, Content.id == Document.content_id)
            .where(Document.course_id == args.course_id)
        ).all()
    names = {name for name, _, _ in rows}
    if len(rows) != len(expected) or names != set(expected):
        print(f"Course {args.course_id} must hold exactly: {sorted(expected)}; found {sorted(names)}", file=sys.stderr)
        return 2
    mismatched = sorted(name for name, _, digest in rows if expected[name] != digest)
    if mismatched:
        print(f"SHA-256 differs from the benchmark PDFs: {mismatched}", file=sys.stderr)
        return 2

    failed = False
    for content_id in sorted({content_id for _, content_id, _ in rows}):
        with factory() as db:
            content = db.get(Content, content_id)
            if content.status != "ready":
                process_content(db, content)
        with factory() as db:
            status = db.get(Content, content_id).status
            chunks = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.content_id == content_id))
        line = f"content_id={content_id} status={status} chunks={chunks}"
        if status != "ready":
            failed = True
        elif not args.parse_only:
            with factory() as db:
                try:
                    result = embed_content(db, content_id)
                except EmbeddingGenerationError:
                    failed = True
                    line += " embedding=failed"
                else:
                    line += f" embedded={result['generated']} skipped={result['skipped']}"
        print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
