import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import embeddings
from app.models.course import Course


@pytest.fixture()
def topics():
    path = Path(__file__).resolve().parents[3] / "evals/retrieval/topics.json"
    return json.loads(path.read_text())


@pytest.fixture()
def geometry_provider(topics, monkeypatch):
    # Only the embedding service is replaced; generation and PostgreSQL ranking
    # stay real. This validates vector geometry, not OpenAI model quality.
    vectors = {item.get("text", item.get("query")): item["geometry_direction"] + [0.0] * 1533
               for item in topics["documents"] + topics["queries"]}
    monkeypatch.setattr(embeddings, "embed_text", lambda value, **kw: vectors[value])


def test_deterministic_topic_evaluation(postgres_factory, topics, geometry_provider):
    from app.retrieval_eval import evaluate_topics
    results = evaluate_topics(postgres_factory, topics)
    assert [result["actual_topic"] for result in results] == ["parallel", "tcp", "accounting"]
    assert all(result["passed"] for result in results)
    assert all(result["scores"][0] > max(result["scores"][1:]) for result in results)


@pytest.mark.parametrize("fail", [False, True])
def test_evaluation_cli_cleans_schema_and_preserves_existing_courses(
    postgres_factory, topics, geometry_provider, monkeypatch, capsys, fail,
):
    from app import retrieval_eval
    with postgres_factory() as db:
        db.add(Course(name="Existing Course remains"))
        db.commit()
        before = db.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'retrieval_eval_%'" )).all()
    if fail:
        def unavailable(*args, **kwargs):
            raise embeddings.EmbeddingError("Private provider error")
        monkeypatch.setattr(embeddings, "embed_text", unavailable)
    assert retrieval_eval.main([]) == (1 if fail else 0)
    with postgres_factory() as db:
        assert db.scalar(select(Course.name)) == "Existing Course remains"
        after = db.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'retrieval_eval_%'" )).all()
    assert after == before
    output = capsys.readouterr()
    assert "Private provider error" not in output.err
    if not fail:
        assert all(item["passed"] for item in json.loads(output.out)["results"])


def test_evaluation_requires_explicit_test_database(monkeypatch, capsys):
    from app.retrieval_eval import main
    monkeypatch.delenv("TEST_POSTGRES_URL", raising=False)
    assert main([]) == 2
    assert "TEST_POSTGRES_URL" in capsys.readouterr().err


def test_live_model_topic_quality(postgres_factory, topics):
    if os.getenv("RUN_LIVE_EMBEDDING_EVAL") != "1":
        pytest.skip("Set RUN_LIVE_EMBEDDING_EVAL=1 and OPENAI_API_KEY for real model quality")
    from app.retrieval_eval import evaluate_topics
    assert all(item["passed"] for item in evaluate_topics(postgres_factory, topics))


def test_topic_tie_does_not_count_as_semantic_success(postgres_factory, topics, monkeypatch):
    from app.retrieval_eval import evaluate_topics
    monkeypatch.setattr(embeddings, "embed_text", lambda value, **kw: [1.0] + [0.0] * 1535)
    results = evaluate_topics(postgres_factory, topics)
    assert results[0]["actual_topic"] == "parallel"  # Deterministic ID tiebreak alone is insufficient.
    assert results[0]["scores"] == [1.0, 1.0, 1.0]
    assert results[0]["passed"] is False
