"""Focused PostgreSQL checks; opt in with TEST_POSTGRES_URL.

Every test owns a temporary schema. No course database tables are touched.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.chunk import Chunk
from app.models.content import Content
from app.parsing import ContentProcessingError, process_content


@pytest.fixture()
def postgres_factory():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to run PostgreSQL integration checks")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("TEST_POSTGRES_URL must point to PostgreSQL")
    schema = f"processing_test_{uuid.uuid4().hex}"
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_engine = engine.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(scoped_engine)
        yield sessionmaker(bind=scoped_engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def _seed(factory, *, ready=False):
    with factory() as db:
        content = Content(
            content_hash="a" * 64, storage_key="storage/a.pdf",
            file_type="application/pdf", status="ready" if ready else "uploaded",
        )
        db.add(content)
        db.flush()
        if ready:
            db.add(Chunk(content_id=content.id, text="Old valid text.", page_number=3, chunk_index=0))
        db.commit()
        return content.id


def _snapshot(db, content_id):
    return list(db.execute(select(Chunk.text, Chunk.page_number, Chunk.chunk_index)
                           .where(Chunk.content_id == content_id)
                           .order_by(Chunk.chunk_index)).all())


def test_postgres_waiting_failed_attempt_preserves_winner(postgres_factory, monkeypatch):
    """A stale session must wait for the row owner and then use its ready state."""
    content_id = _seed(postgres_factory)
    contender_loaded = threading.Event()
    owner_extracting = threading.Event()
    release_owner = threading.Event()
    contender_pid = []
    owner_thread = []

    def extract(path):
        if threading.get_ident() == owner_thread[0]:
            owner_extracting.set()
            assert release_owner.wait(10), "Owner release timed out"
            return ["Winning canonical text."]
        raise RuntimeError("Waiting stale attempt fails during extraction")

    monkeypatch.setattr("app.parsing.extract_pdf_pages", extract)

    def contender():
        with postgres_factory() as db:
            content = db.get(Content, content_id)
            contender_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            contender_loaded.set()
            assert owner_extracting.wait(10), "Owner did not start"
            with pytest.raises(ContentProcessingError):
                process_content(db, content)

    def owner():
        owner_thread.append(threading.get_ident())
        with postgres_factory() as db:
            process_content(db, db.get(Content, content_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting = pool.submit(contender)
        try:
            assert contender_loaded.wait(10), "Contender did not load stale Content"
            winning = pool.submit(owner)
            assert owner_extracting.wait(10), "Owner did not start extraction"
            deadline = time.monotonic() + 5
            blocked = False
            with postgres_factory() as observer:
                while time.monotonic() < deadline:
                    # pg_stat_activity snapshots can be cached in a transaction.
                    observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                    blocked = observer.scalar(text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": contender_pid[0]})
                    if blocked or waiting.done():
                        break
                    threading.Event().wait(0.01)
                assert blocked, "Competing process did not wait for the Content row lock"
                # No intermediate processing state or partial chunks are public.
                assert observer.get(Content, content_id).status == "uploaded"
                assert _snapshot(observer, content_id) == []
        finally:
            release_owner.set()
        winning.result(timeout=10)
        waiting.result(timeout=10)

    with postgres_factory() as db:
        assert db.get(Content, content_id).status == "ready"
        assert _snapshot(db, content_id) == [("Winning canonical text.", 1, 0)]


def test_postgres_replacement_failure_preserves_old_chunks(postgres_factory, monkeypatch):
    content_id = _seed(postgres_factory, ready=True)
    monkeypatch.setattr("app.parsing.extract_pdf_pages", lambda path: ["New first page.", "New second page."])
    with postgres_factory() as db:
        def fail_after_insert(session, context):
            if any(isinstance(item, Chunk) for item in session.new):
                raise RuntimeError("Failure after PostgreSQL replacement inserts")

        event.listen(db, "after_flush", fail_after_insert)
        with pytest.raises(ContentProcessingError):
            process_content(db, db.get(Content, content_id))

    with postgres_factory() as db:
        assert db.get(Content, content_id).status == "ready"
        assert _snapshot(db, content_id) == [("Old valid text.", 3, 0)]


def test_postgres_successful_refresh_is_canonical(postgres_factory, monkeypatch):
    content_id = _seed(postgres_factory, ready=True)
    monkeypatch.setattr("app.parsing.extract_pdf_pages", lambda path: ["New first page.", "New second page."])
    with postgres_factory() as db:
        process_content(db, db.get(Content, content_id))
    with postgres_factory() as db:
        assert db.get(Content, content_id).status == "ready"
        assert _snapshot(db, content_id) == [("New first page.", 1, 0), ("New second page.", 2, 1)]


def test_postgres_constraint_failure_rolls_back_replacement(postgres_factory, monkeypatch):
    """A real PostgreSQL transaction error must recover through the savepoint."""
    content_id = _seed(postgres_factory, ready=True)
    monkeypatch.setattr("app.parsing.extract_pdf_pages", lambda path: ["First new page.", "Second new page."])
    with postgres_factory() as db:
        def duplicate_index(session, context, instances):
            for item in session.new:
                if isinstance(item, Chunk):
                    item.chunk_index = 0

        event.listen(db, "before_flush", duplicate_index)
        with pytest.raises(ContentProcessingError) as error:
            process_content(db, db.get(Content, content_id))
        assert isinstance(error.value.__cause__, IntegrityError)
        assert error.value.__cause__.orig.sqlstate == "23505"

    with postgres_factory() as db:
        assert db.get(Content, content_id).status == "ready"
        assert _snapshot(db, content_id) == [("Old valid text.", 3, 0)]
