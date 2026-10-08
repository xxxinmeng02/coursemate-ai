from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import embeddings
from app.database import get_db
from app.main import app
from app.models.course import Course


@pytest.fixture()
def client_for():
    @contextmanager
    def client(factory):
        def get_session():
            with factory() as db:
                yield db
        app.dependency_overrides[get_db] = get_session
        try:
            with TestClient(app) as test_client:
                yield test_client
        finally:
            app.dependency_overrides.pop(get_db, None)
    return client


@pytest.fixture()
def empty_course(sqlite_factory):
    with sqlite_factory() as db:
        course = Course(name="Empty course")
        db.add(course)
        db.commit()
        return course.id


def test_missing_course_returns_404(sqlite_factory, client_for):
    with client_for(sqlite_factory) as client:
        response = client.post("/courses/999999/search", json={"query": "Parallel speedup"})
    assert response.status_code == 404


def test_empty_course_does_not_require_provider_key(sqlite_factory, empty_course, client_for, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with client_for(sqlite_factory) as client:
        response = client.post(f"/courses/{empty_course}/search", json={"query": "Parallel speedup"})
    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.parametrize("payload", [
    {"query": ""}, {"query": " \t\n "}, {"query": "x" * 2001},
    {"query": "valid", "top_k": 0}, {"query": "valid", "top_k": 51},
    {"query": "valid", "top_k": True}, {"query": "valid", "top_k": 1.5},
    {"top_k": 5},
])
def test_invalid_requests_return_422(sqlite_factory, empty_course, client_for, payload):
    with client_for(sqlite_factory) as client:
        response = client.post(f"/courses/{empty_course}/search", json=payload)
    assert response.status_code == 422


def test_search_response_uses_actual_pgvector(postgres_factory, seed_topics, client_for, monkeypatch):
    topic = seed_topics(postgres_factory)
    monkeypatch.setattr(embeddings, "embed_text", lambda value, **kw: [1.0] + [0.0] * 1535)
    with client_for(postgres_factory) as client:
        response = client.post(f"/courses/{topic['a']}/search", json={"query": "Parallel speedup", "top_k": 1})
    assert response.status_code == 200
    result = response.json()["results"]
    assert len(result) == 1
    assert result[0]["chunk_id"] == topic["parallel"]
    assert result[0]["score"] == pytest.approx(0.8, abs=1e-6)
    assert set(result[0]) == {"chunk_id", "text", "page_number", "document_id", "document_name", "score"}


def test_configurable_default_top_k_and_query_trim(postgres_factory, seed_topics, client_for, monkeypatch):
    topic = seed_topics(postgres_factory)
    monkeypatch.setenv("RETRIEVAL_DEFAULT_TOP_K", "2")

    def embed(value, **kw):
        assert value == "Parallel speedup"
        return [1.0] + [0.0] * 1535

    monkeypatch.setattr(embeddings, "embed_text", embed)
    with client_for(postgres_factory) as client:
        response = client.post(f"/courses/{topic['a']}/search", json={"query": "  Parallel speedup  "})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2


def test_provider_failure_returns_safe_503(postgres_factory, seed_topics, client_for, monkeypatch):
    topic = seed_topics(postgres_factory)

    def fail(*args, **kw):
        raise embeddings.EmbeddingError("Private provider detail")

    monkeypatch.setattr(embeddings, "embed_text", fail)
    with client_for(postgres_factory) as client:
        response = client.post(f"/courses/{topic['a']}/search", json={"query": "Parallel speedup"})
    assert response.status_code == 503
    assert "Private provider detail" not in response.text
