import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import storage
import app.models  # noqa: F401  # register all models on Base.metadata
from app.database import Base, get_db
from app.main import app
from app.models.content import Content
from app.models.document import Document


@pytest.fixture()
def db_session_factory():
    """In-memory SQLite session factory with foreign-key enforcement."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    yield factory

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def storage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def client(db_session_factory, storage_dir):
    """TestClient whose database dependency uses the SQLite session factory."""

    def override_get_db():
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_course(client, name):
    return client.post("/courses", json={"name": name})


def _upload_pdf(
    client,
    course_id,
    content=b"%PDF-1.7\ncourse notes\n%%EOF",
    filename="lecture.pdf",
    content_type="application/pdf",
):
    return client.post(
        f"/courses/{course_id}/documents",
        files={"file": (filename, content, content_type)},
    )


def test_create_course(client):
    response = _create_course(client, "Operating Systems")
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Operating Systems"
    assert "created_at" in body


def test_create_course_trims_whitespace(client):
    response = _create_course(client, "   Algorithms   ")
    assert response.status_code == 201
    assert response.json()["name"] == "Algorithms"


@pytest.mark.parametrize("bad_name", ["", "   ", "\t\n "])
def test_create_course_rejects_blank_name(client, bad_name):
    response = _create_course(client, bad_name)
    assert response.status_code == 422


def test_duplicate_names_get_numeric_suffixes(client):
    names = []
    for _ in range(3):
        response = _create_course(client, "Operating Systems")
        assert response.status_code == 201
        names.append(response.json()["name"])

    assert names == [
        "Operating Systems",
        "Operating Systems (1)",
        "Operating Systems (2)",
    ]


def test_case_sensitive_names_are_distinct(client):
    first = _create_course(client, "Operating Systems")
    second = _create_course(client, "operating systems")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["name"] == "Operating Systems"
    assert second.json()["name"] == "operating systems"


def test_list_courses(client):
    _create_course(client, "Operating Systems")
    _create_course(client, "Algorithms")

    response = client.get("/courses")
    assert response.status_code == 200

    names = [course["name"] for course in response.json()]
    assert names == ["Operating Systems", "Algorithms"]


def test_course_detail_returns_documents_with_status(client, db_session_factory):
    created = _create_course(client, "Operating Systems")
    course_id = created.json()["id"]

    with db_session_factory() as session:
        content = Content(
            content_hash="hash-abc",
            storage_key="uploads/hash-abc.pdf",
            file_type="pdf",
            status="ready",
        )
        session.add(content)
        session.commit()

        session.add(
            Document(
                course_id=course_id,
                content_id=content.id,
                name="lecture1.pdf",
            )
        )
        session.commit()

    response = client.get(f"/courses/{course_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["name"] == "Operating Systems"
    assert len(body["documents"]) == 1

    document = body["documents"][0]
    assert document["name"] == "lecture1.pdf"
    assert document["status"] == "ready"
    assert "created_at" in document

    # Internal content/storage metadata must not leak into the response.
    assert "storage_key" not in document
    assert "content_hash" not in document
    assert "content" not in document


def test_course_detail_missing_returns_404(client):
    response = client.get("/courses/999999")
    assert response.status_code == 404


def test_delete_course_returns_204_and_preserves_content(client, db_session_factory):
    created = _create_course(client, "Operating Systems")
    course_id = created.json()["id"]

    with db_session_factory() as session:
        content = Content(
            content_hash="hash-def",
            storage_key="uploads/hash-def.pdf",
            file_type="pdf",
            status="ready",
        )
        session.add(content)
        session.commit()

        document = Document(
            course_id=course_id,
            content_id=content.id,
            name="lecture1.pdf",
        )
        session.add(document)
        session.commit()

        content_id = content.id
        document_id = document.id

    response = client.delete(f"/courses/{course_id}")
    assert response.status_code == 204
    assert response.content == b""

    # Course no longer exists.
    assert client.get(f"/courses/{course_id}").status_code == 404

    with db_session_factory() as session:
        # Documents are removed with the course via the existing cascade.
        assert session.get(Document, document_id) is None
        # Shared Content is intentionally preserved.
        assert session.get(Content, content_id) is not None


def test_delete_missing_course_returns_404(client):
    response = client.delete("/courses/999999")
    assert response.status_code == 404


def test_root_and_health_endpoints_still_work(client):
    assert client.get("/").json() == {"message": "CourseMate AI API"}
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_pdf_creates_document_and_content(client, db_session_factory, storage_dir):
    course_id = _create_course(client, "Operating Systems").json()["id"]
    content_bytes = b"%PDF-1.7\ncourse notes\n%%EOF"
    expected_hash = hashlib.sha256(content_bytes).hexdigest()

    response = _upload_pdf(client, course_id, content_bytes)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "lecture.pdf"
    assert body["status"] == "uploaded"

    with db_session_factory() as session:
        document = session.get(Document, body["id"])
        content = session.get(Content, document.content_id)
        assert document.course_id == course_id
        assert content.content_hash == expected_hash
        assert content.file_type == "application/pdf"
        assert content.storage_key == f"storage/{expected_hash}.pdf"

    stored_file = storage_dir / f"{expected_hash}.pdf"
    assert stored_file.exists()
    assert stored_file.read_bytes() == content_bytes


def test_upload_pdf_rejects_missing_course(client):
    response = _upload_pdf(client, 999999)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("notes.txt", "application/pdf", b"%PDF-1.7\nvalid-looking"),
        ("notes.pdf", "text/plain", b"%PDF-1.7\nvalid-looking"),
        ("notes.pdf", "application/pdf", b"not a PDF"),
    ],
)
def test_upload_pdf_rejects_non_pdf(client, filename, content_type, content):
    course_id = _create_course(client, "Operating Systems").json()["id"]
    response = client.post(
        f"/courses/{course_id}/documents",
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 400


def test_upload_pdf_rejects_oversized_file(client, storage_dir, monkeypatch):
    monkeypatch.setattr(storage, "MAX_DOCUMENT_SIZE_BYTES", 16)
    course_id = _create_course(client, "Operating Systems").json()["id"]

    response = _upload_pdf(client, course_id, b"%PDF-1.7\nthis is too large")

    assert response.status_code == 413
    assert list(storage_dir.iterdir()) == []


def test_upload_uses_hash_path_instead_of_original_filename(
    client,
    db_session_factory,
    storage_dir,
):
    course_id = _create_course(client, "Operating Systems").json()["id"]
    content_bytes = b"%PDF-1.7\npath traversal check\n%%EOF"
    expected_hash = hashlib.sha256(content_bytes).hexdigest()

    response = _upload_pdf(
        client,
        course_id,
        content_bytes,
        filename="../../escape.pdf",
    )

    assert response.status_code == 201
    assert (storage_dir / f"{expected_hash}.pdf").exists()
    assert not (storage_dir / "escape.pdf").exists()
    with db_session_factory() as session:
        content = session.query(Content).one()
        assert content.storage_key == f"storage/{expected_hash}.pdf"


def test_upload_same_pdf_twice_to_course_returns_conflict(
    client,
    db_session_factory,
    storage_dir,
):
    course_id = _create_course(client, "Operating Systems").json()["id"]
    content_bytes = b"%PDF-1.7\nduplicate\n%%EOF"

    first = _upload_pdf(client, course_id, content_bytes)
    second = _upload_pdf(client, course_id, content_bytes)

    assert first.status_code == 201
    assert second.status_code == 409
    with db_session_factory() as session:
        assert session.query(Document).count() == 1
        assert session.query(Content).count() == 1
    assert len(list(storage_dir.glob("*.pdf"))) == 1


def test_upload_same_pdf_to_two_courses_reuses_content(
    client,
    db_session_factory,
    storage_dir,
):
    first_course_id = _create_course(client, "Operating Systems").json()["id"]
    second_course_id = _create_course(client, "Databases").json()["id"]
    content_bytes = b"%PDF-1.7\nshared\n%%EOF"

    first = _upload_pdf(client, first_course_id, content_bytes)
    second = _upload_pdf(client, second_course_id, content_bytes)

    assert first.status_code == 201
    assert second.status_code == 201
    with db_session_factory() as session:
        documents = session.query(Document).order_by(Document.id).all()
        contents = session.query(Content).all()
        assert len(documents) == 2
        assert len(contents) == 1
        assert {document.course_id for document in documents} == {
            first_course_id,
            second_course_id,
        }
        assert {document.content_id for document in documents} == {contents[0].id}
    assert len(list(storage_dir.glob("*.pdf"))) == 1


def test_upload_database_failure_rolls_back_and_cleans_file(
    client,
    db_session_factory,
    storage_dir,
    monkeypatch,
):
    course_id = _create_course(client, "Operating Systems").json()["id"]

    def fail_commit(self):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = _upload_pdf(client, course_id)

    assert response.status_code == 500
    assert list(storage_dir.iterdir()) == []
    with db_session_factory() as session:
        assert session.query(Document).count() == 0
        assert session.query(Content).count() == 0
