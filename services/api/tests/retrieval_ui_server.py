"""Local UI fixture: real FastAPI routes, SQLite data, scripted search results.

Run only for UI QA: python tests/retrieval_ui_server.py --port 8000
This process never connects to the configured application DB or embedding API.
Search scores/text are fixture data, not a semantic-search quality measurement.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import uvicorn

import app.models  # noqa: F401
from app.database import Base, get_db
from app.embeddings import EmbeddingError
from app.main import app
from app.models.content import Content
from app.models.course import Course
from app.models.document import Document
from app.retrieval import CourseNotFoundError, RetrievalResult
import app.routers.courses as courses_router


def configure_fixture(events_path=None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([Course(id=1, name="UI fixture - Retrieval interaction test"),
                    Course(id=2, name="UI fixture - Second course")])
        content = Content(id=1, content_hash="a" * 64, storage_key="ui-fixture/unused.pdf",
                          file_type="application/pdf", status="ready")
        db.add(content)
        db.flush()
        db.add(Document(id=1, course_id=1, content_id=1, name="MIT6_006S20_lec10.pdf"))
        db.commit()

    def fixture_db():
        with factory() as db:
            yield db

    events = []

    def scripted_search(db, course_id, query, top_k):
        events.append({"course_id": course_id, "query": query, "top_k": top_k})
        if events_path:
            events_path.write_text(json.dumps(events, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        if not db.get(Course, course_id) or query == "__404__":
            raise CourseNotFoundError("Course not found")
        if query == "__503__":
            raise EmbeddingError("UI fixture unavailable")
        if query == "__422__":
            raise HTTPException(422, detail=[{"msg": "UI fixture validation error"}])
        if query == "__empty__" or course_id == 2:
            return []
        time.sleep(2)
        return [
            RetrievalResult(
                chunk_id=100 + i, document_id=1,
                document_name="MIT6_006S20_lec10.pdf" if i != 2 else
                "UI-fixture-" + "long-filename-" * 15 + ".pdf",
                page_number=None if i == 1 else 2 + i,
                score=0.87542 - i * 0.18,
                text=(f"UI FIXTURE ONLY - result {i + 1}.\n"
                      f"Received query: {query}\nReceived top_k: {top_k}\n"
                      "This scripted passage tests UI rendering, not retrieval accuracy.\n"
                      + ("long_unbroken_text_" * 20 if i == 2 else
                         "Source text keeps its line breaks and is rendered as plain text.")),
            ) for i in range(min(top_k, 7))
        ]

    app.dependency_overrides[get_db] = fixture_db
    courses_router.search_course = scripted_search
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--events", type=Path)
    args = parser.parse_args()
    fixture_app = configure_fixture(args.events)
    uvicorn.run(fixture_app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
