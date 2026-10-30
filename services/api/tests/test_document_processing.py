"""Upload-triggered parsing and embedding, observed through the HTTP API."""
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import document_processing, embeddings, storage
import app.models  # noqa: F401
from app.database import Base, get_db, get_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.content import Content
from tests.test_parsing import _pdf_bytes

UNIT_VECTOR = [1.0] + [0.0] * 1535


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_fks(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def client(factory, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_REVISION", raising=False)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: UNIT_VECTOR)

    def get_session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        # TestClient runs background tasks before returning the response.
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        document_processing._in_flight.clear()


def _course(client, name="Algorithms"):
    return client.post("/courses", json={"name": name}).json()["id"]


def _upload(client, course_id, content=None, filename="lecture.pdf"):
    content = content if content is not None else _pdf_bytes(["Dynamic programming."])
    return client.post(f"/courses/{course_id}/documents",
                       files={"file": (filename, content, "application/pdf")})


def _document(client, course_id):
    [document] = client.get(f"/courses/{course_id}").json()["documents"]
    return document


def _fail_if_run(*args, **kwargs):
    pytest.fail("Processing must not be queued")


def test_upload_parses_and_embeds_in_background(client, factory):
    course_id = _course(client)

    response = _upload(client, course_id)

    assert response.status_code == 201
    assert response.json()["processing_state"] == "processing"
    document = _document(client, course_id)
    assert (document["status"], document["processing_state"]) == ("ready", "indexed")
    with factory() as db:
        chunks = db.scalars(select(Chunk)).all()
        assert [chunk.text for chunk in chunks] == ["Dynamic programming."]
        assert all(chunk.embedding == UNIT_VECTOR for chunk in chunks)


def test_embedding_failure_is_retryable(client, monkeypatch):
    course_id = _course(client)

    def unavailable(text, **kwargs):
        raise embeddings.EmbeddingError("Embedding provider is not configured")

    monkeypatch.setattr(embeddings, "embed_text", unavailable)
    _upload(client, course_id)
    document = _document(client, course_id)
    assert (document["status"], document["processing_state"]) == ("ready", "not_indexed")

    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: UNIT_VECTOR)
    retry = client.post(f"/courses/{course_id}/documents/{document['id']}/process")

    assert retry.status_code == 202
    assert retry.json()["processing_state"] == "processing"
    assert _document(client, course_id)["processing_state"] == "indexed"


def test_unparseable_pdf_fails_and_is_not_reprocessed_on_reuse(client, monkeypatch):
    broken = b"%PDF-1.7\nnot really a pdf\n%%EOF"
    first_course, second_course = _course(client, "A"), _course(client, "B")

    _upload(client, first_course, broken)
    document = _document(client, first_course)
    assert (document["status"], document["processing_state"]) == ("failed", "failed")

    monkeypatch.setattr(document_processing, "run_pipeline", _fail_if_run)
    response = _upload(client, second_course, broken)
    assert response.status_code == 201
    assert response.json()["processing_state"] == "failed"


def test_indexed_content_is_reused_without_processing(client, monkeypatch):
    first_course, second_course = _course(client, "A"), _course(client, "B")
    _upload(client, first_course)

    monkeypatch.setattr(document_processing, "run_pipeline", _fail_if_run)
    response = _upload(client, second_course)

    assert response.json()["processing_state"] == "indexed"
    assert _document(client, second_course)["processing_state"] == "indexed"


def test_in_flight_content_reports_processing_and_is_queued_once(client, factory, monkeypatch):
    course_id = _course(client)
    monkeypatch.setattr(document_processing, "run_pipeline", lambda *args: None)
    _upload(client, course_id)  # Claimed, but the stub never releases it.
    document = _document(client, course_id)
    assert document["processing_state"] == "processing"

    monkeypatch.setattr(document_processing, "run_pipeline", _fail_if_run)
    retry = client.post(f"/courses/{course_id}/documents/{document['id']}/process")
    assert retry.status_code == 409
    with factory() as db:
        assert db.scalars(select(Content.status)).one() == "uploaded"


def test_retry_rejects_indexed_and_foreign_documents(client):
    course_id, other_course = _course(client, "A"), _course(client, "B")
    document_id = _upload(client, course_id).json()["id"]

    indexed = client.post(f"/courses/{course_id}/documents/{document_id}/process")
    foreign = client.post(f"/courses/{other_course}/documents/{document_id}/process")

    assert indexed.status_code == 409
    assert foreign.status_code == 404


def test_vectors_from_another_configuration_are_not_indexed(client, monkeypatch):
    course_id = _course(client)
    _upload(client, course_id)

    monkeypatch.setenv("EMBEDDING_REVISION", "v2")
    assert _document(client, course_id)["processing_state"] == "not_indexed"
    monkeypatch.setenv("EMBEDDING_MODEL", "unsupported-model")
    assert _document(client, course_id)["processing_state"] == "not_indexed"


@pytest.fixture(params=["sqlite_factory", "postgres_factory"])
def db_factory(request, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_REVISION", raising=False)
    return request.getfixturevalue(request.param)


def test_processing_states_on_both_databases(db_factory, seed_chunks):
    indexed, _ = seed_chunks(db_factory, embedded=True)
    unembedded, _ = seed_chunks(db_factory)
    failed, _ = seed_chunks(db_factory, status="failed", texts=())
    with db_factory() as db:
        contents = [db.get(Content, content_id) for content_id in (indexed, unembedded, failed)]
        assert document_processing.processing_states(db, contents) == {
            indexed: "indexed", unembedded: "not_indexed", failed: "failed",
        }


def test_pipeline_parses_and_embeds_on_both_databases(db_factory, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: UNIT_VECTOR)
    pdf = _pdf_bytes(["Page one.", "Page two."])
    content_hash = hashlib.sha256(pdf).hexdigest()
    storage.storage_path_for_hash(content_hash).write_bytes(pdf)
    with db_factory() as db:
        content = Content(content_hash=content_hash,
                          storage_key=storage.storage_key_for_hash(content_hash),
                          file_type="application/pdf", status="uploaded")
        db.add(content)
        db.commit()
        content_id = content.id

    assert document_processing.claim(content_id)
    document_processing.run_pipeline(db_factory, content_id)

    assert document_processing.claim(content_id)  # Released after the run.
    document_processing._in_flight.clear()
    with db_factory() as db:
        content = db.get(Content, content_id)
        assert document_processing.processing_states(db, [content]) == {content_id: "indexed"}
        assert [(c.text, c.page_number) for c in content.chunks] == [
            ("Page one.", 1), ("Page two.", 2)]
