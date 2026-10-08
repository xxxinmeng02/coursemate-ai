from contextlib import contextmanager

import pytest
import math
from fastapi.testclient import TestClient

from app import embeddings
from app.database import get_db
from app.main import app
from app.models.course import Course
from app.models.chunk import Chunk


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
    assert response.json() == {"detail": "Course not found"}


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


@pytest.mark.parametrize("magnitude", [1e30, 1e-40])
def test_extreme_existing_and_query_vectors_have_correct_serializable_scores(
    postgres_factory, seed_topics, client_for, monkeypatch, magnitude,
):
    topic = seed_topics(postgres_factory)
    with postgres_factory() as db:
        chunk = db.get(Chunk, topic["parallel"])
        chunk.embedding = [magnitude, magnitude] + [0.0] * 1534
        db.commit()
        before = list(chunk.embedding)
    monkeypatch.setattr(embeddings, "embed_text", lambda value, **kw: [magnitude] + [0.0] * 1535)
    with client_for(postgres_factory) as client:
        response = client.post(f"/courses/{topic['a']}/search", json={"query": "Parallel speedup", "top_k": 3})
    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["chunk_id"] for row in rows] == [topic["parallel"], topic["tcp"], topic["accounting"]]
    assert rows[0]["score"] == pytest.approx(0.70710678, abs=1e-6)
    assert all(math.isfinite(row["score"]) for row in rows)
    with postgres_factory() as db:
        assert list(db.get(Chunk, topic["parallel"]).embedding) == before  # Search stays read-only.


@pytest.mark.parametrize("setting", ["abc", "", "0", "51"])
def test_invalid_server_default_is_safe_503(sqlite_factory, empty_course, client_for, monkeypatch, setting):
    monkeypatch.setenv("RETRIEVAL_DEFAULT_TOP_K", setting)
    with client_for(sqlite_factory) as client:
        response = client.post(f"/courses/{empty_course}/search", json={"query": "Parallel speedup"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Retrieval service unavailable"}


def test_explicit_top_k_does_not_use_invalid_server_default(
    sqlite_factory, empty_course, client_for, monkeypatch,
):
    monkeypatch.setenv("RETRIEVAL_DEFAULT_TOP_K", "abc")
    with client_for(sqlite_factory) as client:
        response = client.post(f"/courses/{empty_course}/search", json={"query": "Parallel speedup", "top_k": 1})
    assert response.status_code == 200
