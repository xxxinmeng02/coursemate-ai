"""Lifecycle races use isolated PostgreSQL schemas, never developer tables."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from test_processing_postgres import postgres_factory
from app import jobs, parsing, storage
from app.models.course import Course
from app.models.content import Content
from app.models.document import Document
from app.models.chunk import Chunk
from app.routers.documents import delete_document


def seed(factory):
    with factory() as db:
        course = Course(name="Lifecycle test")
        content = Content(content_hash="c"*64, storage_key="storage/c.pdf", file_type="application/pdf", status="uploaded")
        db.add_all([course, content]); db.flush()
        doc = Document(course_id=course.id, content_id=content.id, name="test.pdf")
        db.add(doc); db.commit()
        return course.id, content.id, doc.id


def test_postgres_duplicate_document_constraint(postgres_factory):
    course_id, content_id, _ = seed(postgres_factory)
    with postgres_factory() as db:
        db.add(Document(course_id=course_id, content_id=content_id, name="duplicate.pdf"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert len(list(db.scalars(select(Document)))) == 1


def test_postgres_duplicate_jobs_process_once(postgres_factory, monkeypatch):
    _, content_id, _ = seed(postgres_factory)
    extracting, release = threading.Event(), threading.Event()
    calls = []
    def extract(path):
        calls.append(path); extracting.set()
        assert release.wait(10)
        return ["One canonical attempt"]
    monkeypatch.setattr(jobs, "get_session_factory", lambda: postgres_factory)
    monkeypatch.setattr(parsing, "extract_pdf_pages", extract)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(jobs.process_content_job, content_id)
        assert extracting.wait(10)
        second = pool.submit(jobs.process_content_job, content_id)
        release.set()
        first.result(10); second.result(10)
    assert len(calls) == 1
    with postgres_factory() as db:
        assert db.get(Content, content_id).status == "ready"
        assert len(list(db.scalars(select(Chunk)))) == 1


def test_postgres_delete_waits_for_processing_then_cleans(postgres_factory, monkeypatch, tmp_path):
    course_id, content_id, doc_id = seed(postgres_factory)
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    path = storage.storage_path_for_hash("c"*64); path.write_bytes(b"PDF placeholder")
    extracting, release, deleting = threading.Event(), threading.Event(), threading.Event()
    def extract(path):
        extracting.set()
        assert release.wait(10)
        return ["Safe canonical text"]
    monkeypatch.setattr(parsing, "extract_pdf_pages", extract)
    monkeypatch.setattr(jobs, "get_session_factory", lambda: postgres_factory)
    tasks = BackgroundTasks()
    def delete():
        with postgres_factory() as db:
            deleting.set()
            return delete_document(course_id, doc_id, tasks, db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(jobs.process_content_job, content_id)
        assert extracting.wait(10)
        deletion = pool.submit(delete)
        assert deleting.wait(10)
        with postgres_factory() as db:
            assert db.get(Document, doc_id) is not None
            assert path.exists()
        release.set()
        worker.result(10)
        assert deletion.result(10).status_code == 204
    with postgres_factory() as db:
        assert db.get(Content, content_id).status == "pending_cleanup"
        assert db.scalar(select(Chunk)) is not None
    jobs.cleanup_content_job(content_id)
    assert not path.exists()
    with postgres_factory() as db:
        assert db.get(Content, content_id) is None


def test_postgres_retry_waits_for_worker_and_skips_ready(postgres_factory, monkeypatch):
    import time
    from fastapi import Response
    from sqlalchemy import text
    from app.routers.documents import retry_document
    course_id, content_id, doc_id = seed(postgres_factory)
    extracting, release, retry_started = threading.Event(), threading.Event(), threading.Event()
    retry_pid = []
    def extract(path):
        extracting.set()
        assert release.wait(10)
        return ["Winner ready text"]
    monkeypatch.setattr(parsing, "extract_pdf_pages", extract)
    monkeypatch.setattr(jobs, "get_session_factory", lambda: postgres_factory)
    schedule = Mock()
    monkeypatch.setattr(jobs, "schedule_content_processing", schedule)
    def retry():
        with postgres_factory() as db:
            retry_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            retry_started.set()
            return retry_document(course_id, doc_id, BackgroundTasks(), Response(), db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(jobs.process_content_job, content_id)
        assert extracting.wait(10)
        retrier = pool.submit(retry)
        assert retry_started.wait(10)
        try:
            deadline = time.monotonic()+10
            while time.monotonic()<deadline:
                with postgres_factory() as observer:
                    waiting = observer.scalar(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid":retry_pid[0]})
                if waiting == "Lock":
                    break
                time.sleep(.01)
            assert waiting == "Lock", "Retry never waited for the Content lock"
            assert not retrier.done()
        finally:
            release.set()
        worker.result(10)
        assert retrier.result(10).status == "ready"
    schedule.assert_not_called()


def test_postgres_failed_upload_keeps_file_adopted_by_winner(postgres_factory, monkeypatch, tmp_path):
    import asyncio
    from io import BytesIO
    from fastapi import HTTPException, UploadFile
    from starlette.datastructures import Headers
    from sqlalchemy.orm import Session, sessionmaker
    from app.routers.documents import upload_document
    from test_parsing import _pdf_bytes
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    with postgres_factory() as db:
        a, b = Course(name="Loser"), Course(name="Winner")
        db.add_all([a,b]); db.commit()
        a_id,b_id=a.id,b.id
    loser_rolled_back, winner_committed = threading.Event(), threading.Event()
    class FailingSession(Session):
        def commit(self):
            raise RuntimeError("injected upload commit failure")
        def rollback(self):
            super().rollback()
            loser_rolled_back.set()
            assert winner_committed.wait(10)
    failing = sessionmaker(bind=postgres_factory.kw["bind"], class_=FailingSession, autoflush=False)
    payload = _pdf_bytes(["Concurrent shared upload"])
    def upload(factory, course_id):
        file = UploadFile(filename="real.pdf", file=BytesIO(payload), headers=Headers({"content-type":"application/pdf"}))
        with factory() as db:
            return asyncio.run(upload_document(course_id, BackgroundTasks(), file, db))
    with ThreadPoolExecutor(max_workers=2) as pool:
        loser = pool.submit(upload, failing, a_id)
        assert loser_rolled_back.wait(10)
        try:
            winner = pool.submit(upload, postgres_factory, b_id).result(10)
            assert winner.status == "uploaded"
        finally:
            winner_committed.set()
        with pytest.raises(HTTPException) as failure:
            loser.result(10)
        assert failure.value.status_code == 500
    with postgres_factory() as db:
        content = db.scalar(select(Content))
        assert storage.storage_path_for_hash(content.content_hash).read_bytes() == payload
        assert len(list(db.scalars(select(Document)))) == 1
    assert len(list(tmp_path.iterdir())) == 1
