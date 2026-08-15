import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
def client(db_session_factory):
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
