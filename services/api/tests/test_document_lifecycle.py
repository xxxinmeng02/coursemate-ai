from unittest.mock import Mock

import pytest
from sqlalchemy import select

from test_courses_api import db_session_factory, storage_dir, client, _create_course, _upload_pdf
from test_parsing import _pdf_bytes
from app import jobs, parsing, storage
from app.models.content import Content
from app.models.chunk import Chunk


@pytest.fixture(autouse=True)
def worker_database(db_session_factory, monkeypatch):
    monkeypatch.setattr(jobs, "get_session_factory", lambda: db_session_factory)


def test_upload_commits_then_worker_uses_own_session(client, db_session_factory, monkeypatch):
    observed = []
    original = jobs.process_content
    def process(db, content):
        with db_session_factory() as observer:
            assert observer.get(Content, content.id) is not None
        observed.append(db)
        return original(db, content)
    monkeypatch.setattr(jobs, "process_content", process)
    course = _create_course(client, "A").json()["id"]
    response = _upload_pdf(client, course, _pdf_bytes(["Real lecture text"]))
    assert response.status_code == 201
    assert response.json()["status"] == "uploaded"
    assert len(observed) == 1
    assert client.get(f"/courses/{course}").json()["documents"][0]["status"] == "ready"
    with db_session_factory() as db:
        assert db.scalars(select(Chunk)).one().text == "Real lecture text"


def test_shared_ready_skips_processing_and_deletes_only_last_reference(client, db_session_factory, storage_dir, monkeypatch):
    a = _create_course(client, "A").json()["id"]
    b = _create_course(client, "B").json()["id"]
    pdf = _pdf_bytes(["Shared lecture"])
    first = _upload_pdf(client, a, pdf).json()
    parse = Mock(side_effect=AssertionError("ready content was reprocessed"))
    monkeypatch.setattr(jobs, "process_content", parse)
    second = _upload_pdf(client, b, pdf).json()
    assert second["status"] == "ready"
    assert client.delete(f"/courses/{a}/documents/{first['id']}").status_code == 204
    assert len(list(storage_dir.glob("*.pdf"))) == 1
    assert client.get(f"/courses/{b}").json()["documents"][0]["status"] == "ready"
    assert client.delete(f"/courses/{b}/documents/{second['id']}").status_code == 204
    with db_session_factory() as db:
        assert db.scalar(select(Content)) is None
        assert db.scalar(select(Chunk)) is None
    assert list(storage_dir.iterdir()) == []
    parse.assert_not_called()


def test_failed_upload_retry_and_scoping(client, monkeypatch):
    a = _create_course(client, "A").json()["id"]
    b = _create_course(client, "B").json()["id"]
    real_extract = parsing.extract_pdf_pages
    monkeypatch.setattr(parsing, "extract_pdf_pages", Mock(side_effect=RuntimeError("injected")))
    response = _upload_pdf(client, a, _pdf_bytes(["Recoverable PDF"]))
    assert response.status_code == 201
    doc = response.json()["id"]
    assert client.get(f"/courses/{a}").json()["documents"][0]["status"] == "failed"
    assert client.post(f"/courses/{b}/documents/{doc}/retry").status_code == 404
    monkeypatch.setattr(parsing, "extract_pdf_pages", real_extract)
    retry = client.post(f"/courses/{a}/documents/{doc}/retry")
    assert retry.status_code == 202 and retry.json()["status"] == "uploaded"
    assert client.get(f"/courses/{a}").json()["documents"][0]["status"] == "ready"
    assert client.post(f"/courses/{a}/documents/{doc}/retry").status_code == 200


def test_scheduling_failure_does_not_undo_upload(client, monkeypatch):
    monkeypatch.setattr(jobs.BackgroundTasks, "add_task", Mock(side_effect=RuntimeError("scheduler")))
    course = _create_course(client, "A").json()["id"]
    response = _upload_pdf(client, course, _pdf_bytes(["Queued PDF"]))
    assert response.status_code == 201
    assert client.get(f"/courses/{course}").json()["documents"][0]["status"] == "uploaded"


@pytest.mark.parametrize("state", ["ready", "failed", "processing", "pending_cleanup"])
def test_worker_skips_ineligible_states(client, db_session_factory, monkeypatch, state):
    course = _create_course(client, "A").json()["id"]
    _upload_pdf(client, course)
    with db_session_factory() as db:
        content = db.scalar(select(Content))
        content.status = state
        content_id = content.id
        db.commit()
    processor = Mock(side_effect=AssertionError("ineligible"))
    monkeypatch.setattr(jobs, "process_content", processor)
    jobs.process_content_job(content_id)
    processor.assert_not_called()


def test_unlink_failure_retains_pending_tombstone_for_cleanup_retry(client, db_session_factory, monkeypatch, storage_dir):
    course = _create_course(client, "A").json()["id"]
    doc = _upload_pdf(client, course, _pdf_bytes(["Cleanup PDF"])).json()["id"]
    original = storage.cleanup_owned_file
    monkeypatch.setattr(storage, "cleanup_owned_file", Mock(side_effect=OSError("injected unlink")))
    assert client.delete(f"/courses/{course}/documents/{doc}").status_code == 204
    with db_session_factory() as db:
        content = db.scalar(select(Content))
        assert content.status == "pending_cleanup"
        content_id = content.id
    assert len(list(storage_dir.glob("*.pdf"))) == 1
    assert _upload_pdf(client, course, _pdf_bytes(["Cleanup PDF"])).status_code == 409
    monkeypatch.setattr(storage, "cleanup_owned_file", original)
    jobs.cleanup_content_job(content_id)
    with db_session_factory() as db:
        assert db.get(Content, content_id) is None
    assert list(storage_dir.iterdir()) == []


def test_cleanup_commit_failure_leaves_retryable_tombstone(client, db_session_factory, monkeypatch, storage_dir):
    from sqlalchemy.orm import Session, sessionmaker
    course = _create_course(client, "Commit failure").json()["id"]
    doc = _upload_pdf(client, course, _pdf_bytes(["Cleanup commit PDF"])).json()["id"]
    class FailingSession(Session):
        def commit(self):
            raise RuntimeError("cleanup commit failed")
    failing = sessionmaker(bind=db_session_factory.kw["bind"], class_=FailingSession)
    monkeypatch.setattr(jobs, "get_session_factory", lambda: failing)
    assert client.delete(f"/courses/{course}/documents/{doc}").status_code == 204
    with db_session_factory() as db:
        content = db.scalar(select(Content))
        assert content.status == "pending_cleanup"
        content_id = content.id
        assert db.scalar(select(Chunk)) is not None
    assert list(storage_dir.glob("*.pdf")) == []
    monkeypatch.setattr(jobs, "get_session_factory", lambda: db_session_factory)
    jobs.cleanup_content_job(content_id)
    with db_session_factory() as db:
        assert db.get(Content, content_id) is None


def test_worker_closes_dedicated_session_after_failure(client, db_session_factory, monkeypatch):
    from sqlalchemy.orm import Session, sessionmaker
    course = _create_course(client, "Closure").json()["id"]
    doc = _upload_pdf(client, course).json()
    with db_session_factory() as db:
        content = db.scalar(select(Content))
        content.status = "uploaded"
        content_id = content.id
        db.commit()
    closed = []
    class TrackedSession(Session):
        def close(self):
            closed.append(self)
            super().close()
    factory = sessionmaker(bind=db_session_factory.kw["bind"], class_=TrackedSession)
    monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
    monkeypatch.setattr(jobs, "process_content", Mock(side_effect=RuntimeError("worker")))
    jobs.process_content_job(content_id)
    assert len(closed) == 1
    assert client.get(f"/courses/{course}").json()["documents"][0]["id"] == doc["id"]


@pytest.mark.parametrize("state,expected", [("uploaded",202),("processing",200),("pending_cleanup",409)])
def test_retry_remaining_states_without_duplicate_processing(client, db_session_factory, monkeypatch, state, expected):
    course = _create_course(client, "States").json()["id"]
    doc = _upload_pdf(client, course).json()["id"]
    with db_session_factory() as db:
        content = db.scalar(select(Content))
        content.status = state
        db.commit()
    schedule = Mock()
    monkeypatch.setattr(jobs, "schedule_content_processing", schedule)
    response = client.post(f"/courses/{course}/documents/{doc}/retry")
    assert response.status_code == expected
    assert schedule.call_count == (1 if state == "uploaded" else 0)


def test_staging_disposal_error_does_not_hide_committed_upload(client, monkeypatch):
    course = _create_course(client, "Staging disposal").json()["id"]
    monkeypatch.setattr(storage, "discard_staged_upload", Mock(side_effect=OSError("staging cleanup")))
    response = _upload_pdf(client, course, _pdf_bytes(["Committed document"]))
    assert response.status_code == 201
    assert client.get(f"/courses/{course}").json()["documents"][0]["status"] == "ready"
