"""Full-ranking/provenance contracts; controlled vectors are not quality data."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import builtins

import pytest

EVAL_ROOT = Path(__file__).resolve().parents[3] / "evals/retrieval"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, EVAL_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evaluation(monkeypatch):
    monkeypatch.syspath_prepend(str(EVAL_ROOT))
    return load_script("evaluate_mit")


def declaration():
    return {
        "provider": "openai", "model": "text-embedding-3-small", "revision": "v1",
        "native_dimensions": 1536, "stored_dimensions": 1536,
        "storage_config_id": "openai:text-embedding-3-small:1536:v1",
        "model_revision": None, "source": "operator_declared", "runtime_versions": {},
    }


def hit(i, *, evidence=False):
    return dict(chunk_id=i, document_id=9, document_name="notes.pdf", page_number=2,
                text="Required evidence" if evidence else f"Unrelated passage {i}",
                score=1.0 - i / 100)


def corpus():
    return [hit(i, evidence=i == 6) for i in range(1, 8)]


def manifest(hits):
    return [{"document_name": h["document_name"], "page_number": h["page_number"],
             "text_sha256": hashlib.sha256(h["text"].encode()).hexdigest()} for h in hits]


def dataset():
    return {"id": "test-only", "documents": [{"name": "notes.pdf", "sha256": "x"}],
            "questions": [{"id": "Q1", "question": "Student question",
                           "expected_document": "notes.pdf", "expected_page": 2,
                           "evidence_anchor": "Required evidence"}]}


def fetch_for(hits):
    def fetch(url, body=None):
        if body is None:
            return {"documents": [{"id": 9, "name": "notes.pdf", "status": "ready"}]}
        assert body["top_k"] == 8  # Seven expected chunks plus a probe for an unexpected tail.
        return {"results": hits}
    return fetch


def test_full_mrr_counts_rank_six_but_capped_mrr_does_not(evaluation):
    rows = [{"first_source_page_rank": 1, "first_anchor_rank": rank}
            for rank in (1, 6, None)]
    result = evaluation.summarize(rows, 5, full_ranking=True)
    assert result["mrr"] == pytest.approx(7 / 18)
    assert result["source_page_mrr"] == 1
    assert result["anchor_mrr_at_5"] == pytest.approx(1 / 3)
    assert result["anchor_hit_at_5"] == pytest.approx(1 / 3)


def test_full_run_keeps_every_passage_and_declared_model_identity(evaluation):
    result = evaluation.run(dataset(), "http://test", 1, 5, fetch_for(corpus()),
                            chunk_manifest=manifest(corpus()), embedding_record=declaration())
    assert result["status"] == "completed"
    assert result["ranking_complete"] is True
    assert result["retrieval_top_k"] == 8 and result["top_k"] == 5
    assert result["metrics"]["mrr"] == pytest.approx(1 / 6)
    assert result["metrics"]["anchor_mrr_at_5"] == 0
    assert result["metrics"]["anchor_hit_at_5"] == 0
    assert len(result["results"][0]["hits"]) == 7
    assert result["results"][0]["first_anchor_rank"] == 6
    assert result["embedding"]["provider"] == "openai"
    assert result["embedding"]["verification"] == "not_verified_by_search_api"
    assert "full-course" in result["latency_scope"]


@pytest.mark.parametrize("broken", ["missing", "changed_text", "wrong_page", "extra"])
def test_incomplete_or_different_corpus_has_no_full_mrr(evaluation, broken):
    actual = corpus()
    if broken == "missing":
        actual = actual[:-1]
    elif broken == "changed_text":
        actual[0] = {**actual[0], "text": "Foreign text on a valid document page"}
    elif broken == "wrong_page":
        actual[0] = {**actual[0], "page_number": 3}
    else:
        actual.append(hit(8))
    result = evaluation.run(dataset(), "http://test", 1, 5, fetch_for(actual),
                            chunk_manifest=manifest(corpus()), embedding_record=declaration())
    assert result["status"] == "blocked"
    assert result["metrics"] is None
    assert not result["ranking_complete"]


def test_full_manifest_preserves_duplicate_text_multiplicity(evaluation):
    expected = corpus()
    expected[1] = {**expected[1], "text": expected[0]["text"]}
    actual = [*expected[:-1], {**expected[-1], "text": expected[0]["text"]}]
    result = evaluation.run(dataset(), "http://test", 1, 5, fetch_for(actual),
                            chunk_manifest=manifest(expected), embedding_record=declaration())
    assert result["status"] == "blocked" and result["metrics"] is None


def test_canonical_ids_cannot_change_between_questions(evaluation):
    fixture = dataset()
    fixture["questions"].append({**fixture["questions"][0], "id": "Q2"})
    calls = 0
    def fetch(url, body=None):
        nonlocal calls
        if body is None:
            return fetch_for(corpus())(url)
        calls += 1
        return {"results": [dict(h, chunk_id=h["chunk_id"] + (100 if calls > 1 else 0))
                            for h in corpus()]}
    result = evaluation.run(fixture, "http://test", 1, 5, fetch,
                            chunk_manifest=manifest(corpus()), embedding_record=declaration())
    assert result["status"] == "blocked" and result["metrics"] is None
    assert len(result["results"]) == 1


@pytest.mark.parametrize("size", [0, 51])
def test_unprovable_full_ranking_blocks_before_http(evaluation, size):
    def no_request(*args, **kwargs):
        pytest.fail("Invalid full evaluation must not make HTTP calls")
    result = evaluation.run(dataset(), "http://test", 1, 5, no_request,
                            chunk_manifest=manifest([hit(i) for i in range(size)]),
                            embedding_record=declaration())
    assert result["status"] == "blocked" and result["metrics"] is None


def test_full_mode_requires_model_identity_before_http(evaluation):
    def no_request(*args, **kwargs):
        pytest.fail("Missing provenance must block before HTTP")
    result = evaluation.run(dataset(), "http://test", 1, 5, no_request,
                            chunk_manifest=manifest(corpus()))
    assert result["status"] == "blocked" and result["metrics"] is None


def test_requested_limit_cannot_hide_extra_trailing_course_chunks(evaluation):
    def fetch(url, body=None):
        if body is None:
            return fetch_for(corpus())(url)
        # A real API obeys top-k. The extra chunk ranks below the verified seven.
        return {"results": [*corpus(), hit(8)][:body["top_k"]]}
    result = evaluation.run(dataset(), "http://test", 1, 5, fetch,
                            chunk_manifest=manifest(corpus()), embedding_record=declaration())
    assert result["status"] == "blocked"
    assert result["metrics"] is None and not result["ranking_complete"]


def test_manifest_at_api_cap_cannot_prove_absence_of_more_chunks(evaluation):
    def no_request(*args, **kwargs):
        pytest.fail("At the API cap an extra chunk cannot be probed")
    result = evaluation.run(dataset(), "http://test", 1, 5, no_request,
                            chunk_manifest=manifest([hit(i) for i in range(50)]),
                            embedding_record=declaration())
    assert result["status"] == "blocked" and result["metrics"] is None


@pytest.mark.parametrize("change", [
    {"api_key": "SECRET-MUST-NOT-BE-RECORDED"}, {"native_dimensions": True},
    {"native_dimensions": 0}, {"native_dimensions": 2048},
    {"revision": ""}, {"model": ""}, {"stored_dimensions": 384},
    {"storage_config_id": "openai:text-embedding-3-small:1536:another-version"},
])
def test_invalid_or_secret_model_record_is_rejected(monkeypatch, tmp_path, change):
    monkeypatch.syspath_prepend(str(EVAL_ROOT))
    records = load_script("embedding_record")
    path = tmp_path / "model.json"
    path.write_text(json.dumps({**declaration(), **change}))
    with pytest.raises(ValueError) as error:
        records.load_embedding_record(path)
    assert "SECRET-MUST-NOT-BE-RECORDED" not in str(error.value)


def test_record_does_not_invent_upstream_version_or_server_verification(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(EVAL_ROOT))
    records = load_script("embedding_record")
    path = tmp_path / "model.json"
    path.write_text(json.dumps(declaration()))
    result = records.load_embedding_record(path)
    assert result["model_revision"] is None
    assert result["source"] == "operator_declared"
    assert result["verification"] == "not_verified_by_search_api"


def test_local_receipt_records_bge_and_preserves_legacy_storage_identity(monkeypatch, tmp_path):
    from app import embeddings
    monkeypatch.syspath_prepend(str(EVAL_ROOT))
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_REVISION", "v1")
    monkeypatch.setattr(embeddings, "embed_text", embeddings.embed_text)
    local = load_script("local_embeddings")
    path = tmp_path / "local.json"
    local.write_runtime_record(path)
    result = json.loads(path.read_text())
    assert result["provider"] == "fastembed"
    assert result["model"] == "BAAI/bge-small-en-v1.5"
    assert result["native_dimensions"] == 384
    assert result["stored_dimensions"] == 1536
    assert result["storage_config_id"] == "openai:text-embedding-3-small:1536:local-bge-small-en-v1.5"
    assert result["model_revision"] is None
    assert result["source"] == "local_runtime_receipt"
    assert local._model is None  # Receipt generation must not load/download a model.
    with pytest.raises(FileExistsError):
        local.write_runtime_record(path)


def test_local_api_receipt_is_written_after_app_environment_initialization(monkeypatch, tmp_path):
    from app import embeddings
    import uvicorn
    monkeypatch.syspath_prepend(str(EVAL_ROOT))
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("EMBEDDING_REVISION", "v1")
    monkeypatch.setattr(embeddings, "embed_text", embeddings.embed_text)
    local = load_script("local_embeddings")
    real_import = builtins.__import__
    def load_app_environment(name, *args, **kwargs):
        result = real_import(name, *args, **kwargs)
        if name == "app.main":
            # Reproduce a model configured only by app.database's .env loading.
            monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
        return result
    monkeypatch.setattr(builtins, "__import__", load_app_environment)
    served_config = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs:
                        served_config.append(embeddings.get_embedding_config().identifier))
    output = tmp_path / "runtime.json"
    assert local.main(["api", "--record-output", str(output)]) == 0
    assert json.loads(output.read_text())["storage_config_id"] == served_config[0]
    assert served_config[0] == "openai:text-embedding-3-large:1536:local-bge-small-en-v1.5"


def test_verified_pdf_manifest_has_one_entry_per_actual_chunk(evaluation):
    directory = EVAL_ROOT / "sources"
    fixture = evaluation.load_dataset()
    if not all((directory / d["name"]).exists() for d in fixture["documents"]):
        pytest.skip("Download PDFs for offline manifest verification")
    result = evaluation.validate_sources(fixture, directory)
    assert len(result["chunk_manifest"]) == result["chunk_count"] == 46
    counts = Counter(c["document_name"] for c in result["chunk_manifest"])
    assert len(counts) == 5
    assert all(len(c["text_sha256"]) == 64 for c in result["chunk_manifest"])


def test_cli_requires_explicit_record_instead_of_guessing_openai(evaluation, tmp_path):
    with pytest.raises(SystemExit) as error:
        evaluation.main(["run", "--course-id", "1", "--output", str(tmp_path / "result.json")])
    assert error.value.code == 2
    assert not (tmp_path / "result.json").exists()


def test_cli_keeps_full_http_results_and_model_record(evaluation, monkeypatch, tmp_path, capsys):
    # Only PDF extraction is replaced; exercise the CLI, actual HTTP, ranking and JSON output.
    monkeypatch.setattr(evaluation, "load_dataset", dataset)
    monkeypatch.setattr(evaluation, "validate_sources", lambda *args: {
        "chunk_manifest": manifest(corpus()), "chunk_count": 7, "pdf_checksums_verified": True,
    })
    record = tmp_path / "model.json"
    record.write_text(json.dumps(declaration()))
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, value):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            self.send_json({"documents": [{"id": 9, "name": "notes.pdf", "status": "ready"}]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload == {"query": "Student question", "top_k": 8}
            self.send_json({"results": corpus()})

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "result.json"
    args = ["run", "--course-id", "1", "--output", str(output),
            "--embedding-record", str(record), "--api-url", f"http://127.0.0.1:{server.server_port}"]
    try:
        assert evaluation.main(args) == 0
        result = json.loads(output.read_text())
        assert result["ranking_complete"] is True
        assert result["metrics"]["mrr"] == pytest.approx(1 / 6)
        assert result["metrics"]["anchor_mrr_at_5"] == 0
        assert result["embedding"]["model"] == "text-embedding-3-small"
        original = output.read_bytes()
        with pytest.raises(SystemExit) as error:
            evaluation.main(args)
        assert error.value.code == 2 and output.read_bytes() == original
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_invalid_model_file_stops_cli_without_exposing_secret(evaluation, monkeypatch, tmp_path, capsys):
    record = tmp_path / "model.json"
    record.write_text(json.dumps({**declaration(), "api_key": "SECRET-MUST-NOT-BE-RECORDED"}))
    def forbidden(*args):
        pytest.fail("Invalid model record must stop before source extraction or HTTP")
    monkeypatch.setattr(evaluation, "validate_sources", forbidden)
    assert evaluation.main(["run", "--course-id", "1", "--embedding-record", str(record),
                            "--output", str(tmp_path / "result.json")]) == 2
    captured = capsys.readouterr()
    assert "SECRET-MUST-NOT-BE-RECORDED" not in captured.out + captured.err
    assert not (tmp_path / "result.json").exists()
