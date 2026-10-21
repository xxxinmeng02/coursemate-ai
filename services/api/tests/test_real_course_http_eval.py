"""Evaluation-tool regressions only; no synthetic scores imply model quality."""
import importlib.util
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "evals/retrieval/evaluate_mit.py"
spec = importlib.util.spec_from_file_location("evaluate_mit", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def hit(name="notes.pdf", page=2, text="Required evidence", chunk_id=1, score=0.8):
    return dict(document_name=name, page_number=page, text=text,
                document_id=9, chunk_id=chunk_id, score=score)


def case():
    return dict(id="Q1", question="Student question", expected_document="notes.pdf",
                expected_page=2, evidence_anchor="Required evidence")


def test_grading_requires_source_page_and_anchor_not_just_a_similar_filename():
    result = evaluation.grade(case(), [
        hit(page=3), hit(name="other.pdf"), hit(text="An unrelated paragraph", chunk_id=3),
        hit(text="Required\n evidence", chunk_id=4),
    ])
    assert result == {"first_source_page_rank": 3, "first_anchor_rank": 4}


def test_alternative_page_is_accepted_but_null_page_is_not():
    question = {**case(), "alternative_sources": [{
        "document_name": "notes.pdf", "page_number": 4, "evidence_anchor": "other evidence",
    }]}
    assert evaluation.grade(question, [hit(page=None), hit(page=4, text="other evidence")]) == {
        "first_source_page_rank": 2, "first_anchor_rank": 2,
    }


def test_misses_remain_in_the_denominator_and_mrr_is_capped():
    rows = [
        {"first_source_page_rank": 1, "first_anchor_rank": 2},
        {"first_source_page_rank": None, "first_anchor_rank": None},
    ]
    metrics = evaluation.summarize(rows, 5)
    assert metrics["source_page_hit_at_1"] == 0.5
    assert metrics["anchor_hit_at_1"] == 0
    assert metrics["anchor_hit_at_3"] == 0.5
    assert metrics["anchor_mrr_at_5"] == 0.25
    assert "mrr" not in metrics


@pytest.mark.parametrize("changed", [
    {"document_id": 100}, {"document_name": "foreign.pdf"}, {"score": float("nan")},
    {"score": True}, {"page_number": 0}, {"page_number": True}, {"text": ""},
])
def test_invalid_or_foreign_results_cannot_produce_a_quality_report(changed):
    with pytest.raises(ValueError):
        evaluation.check_hits([{**hit(), **changed}], {9: "notes.pdf"}, 5)


def test_duplicate_chunks_and_unsorted_scores_are_rejected():
    with pytest.raises(ValueError):
        evaluation.check_hits([hit(), hit()], {9: "notes.pdf"}, 5)
    with pytest.raises(ValueError):
        evaluation.check_hits([hit(score=0.1), hit(chunk_id=2)], {9: "notes.pdf"}, 5)


def test_real_dataset_has_complete_labels_and_same_course_provenance():
    dataset = evaluation.load_dataset()
    assert len(dataset["questions"]) == 25
    assert len(dataset["documents"]) == 5
    assert all(doc["url"].startswith(dataset["course_url"]) for doc in dataset["documents"])


def test_original_pdf_labels_when_sources_have_been_downloaded():
    directory = evaluation.DATASET.with_name("sources")
    if not all((directory / doc["name"]).exists()
               for doc in evaluation.load_dataset()["documents"]):
        pytest.skip("Download MIT PDFs to run source/label verification")
    result = evaluation.validate_sources(evaluation.load_dataset(), directory)
    assert result["pdf_checksums_verified"]
    assert not result["search_quality_measured"]


def fixture():
    return {"id": "test-only", "documents": [{"name": "notes.pdf", "sha256": "x"}],
            "questions": [case()]}


def ready_course():
    return {"documents": [{"id": 9, "name": "notes.pdf", "status": "ready"}]}


@pytest.mark.parametrize("response", [
    {"documents": []},
    {"documents": [{"id": 9, "name": "notes.pdf", "status": "uploaded"}]},
    {"documents": [{"id": 9, "name": "notes.pdf", "status": "ready"},
                   {"id": 10, "name": "extra.pdf", "status": "ready"}]},
])
def test_preflight_blocks_wrong_corpus_before_query_requests(response):
    calls = []
    def fetch(url, body=None):
        calls.append(url)
        return response
    result = evaluation.run(fixture(), "http://test", 1, 5, fetch)
    assert result["status"] == "blocked"
    assert result["metrics"] is None
    assert len(calls) == 1


@pytest.mark.parametrize("error", [
    HTTPError("http://test", 503, "Unavailable", {}, None),
    URLError("not running"),
])
def test_unavailable_service_is_blocked_not_zero_quality(error):
    def fetch(url, body=None):
        raise error
    result = evaluation.run(fixture(), "http://test", 1, 5, fetch)
    assert result["status"] == "blocked"
    assert result["metrics"] is None
    assert not result["search_quality_measured"]


def test_missing_backfill_is_blocked_not_a_success():
    def fetch(url, body=None):
        return {"results": []} if body else ready_course()
    result = evaluation.run(fixture(), "http://test", 1, 5, fetch)
    assert result["status"] == "blocked"
    assert result["metrics"] is None


def test_completed_run_retains_exact_request_results_and_capped_metrics():
    calls = []
    def fetch(url, body=None):
        calls.append((url, body))
        return {"results": [hit()]} if body else ready_course()
    result = evaluation.run(fixture(), "http://test/", 7, 5, fetch)
    assert calls[1] == ("http://test/courses/7/search", {"query": "Student question", "top_k": 5})
    assert result["status"] == "completed"
    assert result["metrics"]["anchor_hit_at_5"] == 1
    assert result["results"][0]["hits"] == [hit()]


def test_partial_failed_run_has_no_aggregate_quality_metrics():
    dataset = {**fixture(), "questions": [case(), {**case(), "id": "Q2"}]}
    count = 0
    def fetch(url, body=None):
        nonlocal count
        if not body:
            return ready_course()
        count += 1
        if count == 2:
            raise URLError("offline")
        return {"results": [hit()]}
    result = evaluation.run(dataset, "http://test", 1, 5, fetch)
    assert result["status"] == "blocked"
    assert len(result["results"]) == 1
    assert result["metrics"] is None
