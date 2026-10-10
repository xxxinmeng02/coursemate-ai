"""Benchmark contracts; synthetic provider tests never establish model quality."""
from collections import Counter
import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import embeddings, retrieval_eval
from app.models.course import Course
from app.retrieval import RetrievalResult


@pytest.fixture()
def small_benchmark():
    return {
        "id": "test-course-v1", "course": "Test course", "provenance": "test only",
        "documents": [{"name": f"lecture-{i}.txt", "pages": [f"Evidence topic {i}."]}
                      for i in range(6)],
        "questions": [
            {"id": "q1", "type": "factual", "question": "Explain the first idea",
             "expected_document": "lecture-0.txt", "expected_page": 1,
             "expected_topic": "first idea", "evidence": "Evidence topic 0."},
            {"id": "q2", "type": "hard", "question": "Explain the last idea",
             "expected_document": "lecture-5.txt", "expected_page": 1,
             "expected_topic": "last idea", "evidence": "Evidence topic 5."},
        ],
    }


def test_course_dataset_labels_resolve_to_real_page_local_chunks():
    # Catches broken golden labels, copied questions, missing categories, and a
    # corpus too small to make Top 5 meaningful. Expectations are human authored.
    fixture = json.loads(retrieval_eval.BENCHMARK_PATH.read_text())
    chunks = retrieval_eval.benchmark_chunks(fixture)
    assert len(fixture["questions"]) == 25
    assert Counter(q["type"] for q in fixture["questions"]) == {
        "factual": 5, "paraphrase": 5, "terminology": 5, "comparison": 5, "hard": 5,
    }
    assert 10 < len(chunks) <= 50
    for case in fixture["questions"]:
        relevant = [c for c in chunks if c["document_name"] == case["expected_document"]
                    and c["page_number"] == case["expected_page"] and case["evidence"] in c["text"]]
        assert relevant, case["id"]
        assert all(case["question"].lower() not in c["text"].lower() for c in chunks)


@pytest.mark.parametrize("broken", ["document", "page", "evidence", "duplicate_id", "duplicate_document"])
def test_invalid_annotations_are_rejected_before_embedding(small_benchmark, broken):
    fixture = copy.deepcopy(small_benchmark)
    if broken == "document":
        fixture["questions"][0]["expected_document"] = "absent.txt"
    elif broken == "page":
        fixture["questions"][0]["expected_page"] = 2
    elif broken == "evidence":
        fixture["questions"][0]["evidence"] = "not in the source"
    elif broken == "duplicate_id":
        fixture["questions"][1]["id"] = "q1"
    else:
        fixture["documents"][1]["name"] = "lecture-0.txt"
    with pytest.raises(ValueError):
        retrieval_eval.benchmark_chunks(fixture)


def test_metrics_use_every_question_and_full_reciprocal_rank():
    rows = [{"first_relevant_rank": rank, "latency_ms": latency}
            for rank, latency in zip([1, 3, 5, 6, None], [10, 20, 30, 40, 50])]
    summary = retrieval_eval.summarize_benchmark(rows)
    assert summary["metrics"] == pytest.approx({
        "recall_at_1": 0.2, "recall_at_3": 0.4, "recall_at_5": 0.6, "mrr": 0.34,
    })
    assert summary["latency_ms"] == {"mean": 30, "median": 30, "p95": 50}


def test_empty_evaluation_cannot_report_success():
    with pytest.raises(ValueError):
        retrieval_eval.summarize_benchmark([])


def test_question_grading_preserves_actual_chunks_and_rank_beyond_five(small_benchmark):
    hits = [RetrievalResult(i, f"Actual passage {i}", 1, 1, "lecture-5.txt", 1 - i / 10)
            for i in range(1, 8)]
    row = retrieval_eval.grade_question(small_benchmark["questions"][1], hits, {6}, 25)
    assert row["first_relevant_rank"] == 6
    assert row["outcome"] == "miss_at_5"
    assert row["top_5"][0]["text"] == "Actual passage 1"
    assert row["top_5"][0]["rank"] == 1
    assert row["expected_hits"][0]["rank"] == 6
    assert row["expected_hits"][0]["text"] == "Actual passage 6"
    assert row["latency_ms"] == 25
    # Same document is insufficient: only the annotated canonical evidence counts.
    assert row["top_5"][0]["relevant"] is False


def test_missing_key_writes_blocked_artifact_without_measurements(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TEST_POSTGRES_URL", "postgresql+psycopg://unused@127.0.0.1:9/unused")
    output = tmp_path / "blocked.json"
    assert retrieval_eval.main(["--benchmark", "--output", str(output)]) == 2
    record = json.loads(output.read_text())
    assert record["status"] == "blocked"
    assert record["question_count"] == 25
    assert record["real_embeddings_used"] is False
    assert all(value is None for value in record["metrics"].values())
    assert record["latency_ms"] is None
    assert record["results"] == []
    assert "OPENAI_API_KEY" in record["blocker"]
    assert json.loads(capsys.readouterr().out) == record


def test_benchmark_requires_explicit_postgres_database(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.delenv("TEST_POSTGRES_URL", raising=False)
    output = tmp_path / "blocked.json"
    assert retrieval_eval.main(["--benchmark", "--output", str(output)]) == 2
    record = json.loads(output.read_text())
    assert record["status"] == "blocked"
    assert "TEST_POSTGRES_URL" in record["blocker"]
    assert record["real_embeddings_used"] is False


@pytest.fixture()
def ordered_provider(monkeypatch):
    def provider(value, **kwargs):
        if value.startswith("Evidence topic"):
            i = int(value.split()[2].rstrip("."))
            return ([1.0, i / 10] if i < 5 else [0.0, 1.0]) + [0.0] * 1534
        return [1.0] + [0.0] * 1535
    monkeypatch.setattr(embeddings, "embed_text", provider)


def test_real_pgvector_benchmark_measures_full_rank_and_keeps_evidence(
    postgres_factory, small_benchmark, ordered_provider,
):
    record = retrieval_eval.evaluate_benchmark(postgres_factory, small_benchmark)
    assert record["question_count"] == 2
    assert record["chunk_count"] == 6
    assert record["metrics"] == pytest.approx({
        "recall_at_1": 0.5, "recall_at_3": 0.5, "recall_at_5": 0.5, "mrr": 7 / 12,
    })
    assert record["results"][1]["first_relevant_rank"] == 6
    assert record["results"][1]["expected_hits"][0]["text"] == "Evidence topic 5."
    assert len(record["results"][1]["top_5"]) == 5
    assert record["latency_ms"]["mean"] > 0


@pytest.mark.parametrize("fail", [False, True])
def test_benchmark_cli_cleans_schema_on_success_and_provider_failure(
    postgres_factory, small_benchmark, ordered_provider, monkeypatch, tmp_path, fail, capsys,
):
    fixture_path = tmp_path / "dataset.json"
    fixture_path.write_text(json.dumps(small_benchmark))
    monkeypatch.setattr(retrieval_eval, "BENCHMARK_PATH", fixture_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    with postgres_factory() as db:
        db.add(Course(name="Existing course"))
        db.commit()
        before = db.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'retrieval_eval_%'" )).all()
    if fail:
        def unavailable(*args, **kwargs):
            raise embeddings.EmbeddingError("Private provider payload")
        monkeypatch.setattr(embeddings, "embed_text", unavailable)
    output = tmp_path / "result.json"
    assert retrieval_eval.main(["--benchmark", "--output", str(output)]) == (1 if fail else 0)
    record = json.loads(output.read_text())
    assert record["status"] == ("blocked" if fail else "completed")
    assert record["real_embeddings_used"] is (None if fail else True)
    if fail:
        assert all(value is None for value in record["metrics"].values())
        assert record["results"] == []
    with postgres_factory() as db:
        after = db.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'retrieval_eval_%'" )).all()
        assert after == before
        assert db.scalar(select(Course.name)) == "Existing course"
    assert "Private provider payload" not in output.read_text() + capsys.readouterr().err


def test_live_course_benchmark(postgres_factory):
    import os
    if os.getenv("RUN_LIVE_EMBEDDING_EVAL") != "1" or not os.getenv("OPENAI_API_KEY", "").strip():
        pytest.skip("Set RUN_LIVE_EMBEDDING_EVAL=1 and OPENAI_API_KEY for real course quality")
    fixture = json.loads(retrieval_eval.BENCHMARK_PATH.read_text())
    record = retrieval_eval.evaluate_benchmark(postgres_factory, fixture)
    assert len(record["results"]) == 25
    assert all(0 <= value <= 1 for value in record["metrics"].values())


def test_invalid_embedding_configuration_is_a_safe_blocked_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EMBEDDING_MODEL", "unsupported-model")
    output = tmp_path / "blocked.json"
    assert retrieval_eval.main(["--benchmark", "--output", str(output)]) == 2
    record = json.loads(output.read_text())
    assert record["status"] == "blocked"
    assert record["embedding_config"] is None
    assert "configuration" in record["blocker"]
    assert record["real_embeddings_used"] is False
    assert all(value is None for value in record["metrics"].values())


@pytest.mark.parametrize("case_id,document", [
    ("H02", "02-shared-memory-notes.txt"), ("H03", "03-message-passing-notes.txt"),
])
def test_answer_bearing_alternative_counts_as_relevant_before_live_measurement(
    postgres_factory, monkeypatch, case_id, document,
):
    fixture = json.loads(retrieval_eval.BENCHMARK_PATH.read_text())
    case = next(q for q in fixture["questions"] if q["id"] == case_id)
    # Independently reviewed source: both page-2 chunks answer these questions.
    alternative = next(c for c in retrieval_eval.benchmark_chunks(fixture)
                       if c["document_name"] == document and c["chunk_index"] == 3)
    fixture["questions"] = [case]
    def provider(value, **kwargs):
        direction = [1.0, 0.0] if value in (alternative["text"], case["question"]) else [0.0, 1.0]
        return direction + [0.0] * 1534
    monkeypatch.setattr(embeddings, "embed_text", provider)
    record = retrieval_eval.evaluate_benchmark(postgres_factory, fixture)
    assert record["metrics"]["recall_at_1"] == 1
    assert record["metrics"]["mrr"] == 1
    row = record["results"][0]
    assert row["top_5"][0]["text"] == alternative["text"]
    assert row["top_5"][0]["relevant"] is True
    assert len(row["expected_chunk_ids"]) == 2
    unrelated = {**alternative, "text": "This paragraph only discusses broadcasting."}
    assert not retrieval_eval._matches_evidence(case, unrelated)
    assert not retrieval_eval._matches_evidence(case, {**alternative, "page_number": 1})
    assert not retrieval_eval._matches_evidence(case, {**alternative, "document_name": "foreign.txt"})


@pytest.mark.parametrize("invalid", [["Not present on the annotated page"], "Evidence"])
def test_invalid_alternative_evidence_is_not_silently_ignored(small_benchmark, invalid):
    small_benchmark["questions"][0]["alternative_evidence"] = invalid
    with pytest.raises(ValueError):
        retrieval_eval.benchmark_chunks(small_benchmark)
