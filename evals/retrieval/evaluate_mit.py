"""Validate real PDF labels offline, or measure an existing Course's search API.

No production writes, embedding calls, database connections or LLM generation.
The live API itself may make a paid query-embedding request for each question.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATASET = Path(__file__).with_name("mit_6006.json")
API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from embedding_record import load_embedding_record, validate_embedding_record


def normalized(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def load_dataset(path=DATASET):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    documents = fixture["documents"]
    names = [doc["name"] for doc in documents]
    cases = fixture["questions"]
    if len(names) != len(set(names)) or len(cases) != 25:
        raise ValueError("Expected distinct documents and 25 questions")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate question IDs")
    if len({normalized(case["question"]) for case in cases}) != len(cases):
        raise ValueError("Duplicate question wording")
    by_name = {doc["name"]: doc for doc in documents}
    for case in cases:
        for field in ("question", "answer_summary", "locator", "evidence_anchor"):
            if not isinstance(case[field], str) or not case[field].strip():
                raise ValueError(f"Missing annotation: {case['id']} / {field}")
        for source in golden_sources(case):
            doc = by_name.get(source["document_name"])
            page = source["page_number"]
            if (not doc or type(page) is not int or not 1 <= page < doc["pages"]
                    or not isinstance(source["evidence_anchor"], str)
                    or not source["evidence_anchor"].strip()):
                raise ValueError(f"Invalid golden source: {case['id']}")
    return fixture


def golden_sources(case):
    return [{
        "document_name": case["expected_document"],
        "page_number": case["expected_page"],
        "evidence_anchor": case["evidence_anchor"],
    }, *case.get("alternative_sources", [])]


def validate_sources(fixture, directory):
    # Reuse current extraction/chunking, but never modify its implementation.
    sys.path.insert(0, str(API_ROOT))
    from app.parsing import chunk_page, extract_pdf_pages, normalize_text

    pages_by_name = {}
    manifest = []
    for doc in fixture["documents"]:
        path = directory / doc["name"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise ValueError(f"PDF checksum mismatch: {doc['name']}")
        pages = extract_pdf_pages(path)
        if len(pages) != doc["pages"]:
            raise ValueError(f"PDF page count mismatch: {doc['name']}")
        pages_by_name[doc["name"]] = pages
        for number, page in enumerate(pages, 1):
            for passage in chunk_page(normalize_text(page)):
                manifest.append({"document_name": doc["name"], "page_number": number,
                                 "text_sha256": hashlib.sha256(passage.encode()).hexdigest()})
    for case in fixture["questions"]:
        for source in golden_sources(case):
            page = pages_by_name[source["document_name"]][source["page_number"] - 1]
            anchor = normalized(source["evidence_anchor"])
            if anchor not in normalized(page):
                raise ValueError(f"Evidence not found on annotated PDF page: {case['id']}")
            if not any(anchor in normalized(chunk)
                       for chunk in chunk_page(normalize_text(page))):
                raise ValueError(f"Evidence split by current chunker: {case['id']}")
        if any(normalized(case["question"]) in normalized(page)
               for pages in pages_by_name.values() for page in pages):
            raise ValueError(f"Question copied verbatim from source: {case['id']}")
    return {"status": "labels_validated", "question_count": len(fixture["questions"]),
            "document_count": len(fixture["documents"]), "chunk_count": len(manifest),
            "chunk_manifest": manifest,
            "pdf_checksums_verified": True, "search_quality_measured": False}


def grade(case, hits):
    sources = golden_sources(case)
    page_rank = anchor_rank = None
    for rank, hit in enumerate(hits, 1):
        matching = [source for source in sources
                    if hit["document_name"] == source["document_name"]
                    and hit["page_number"] == source["page_number"]]
        if matching and page_rank is None:
            page_rank = rank
        if anchor_rank is None and any(
            normalized(source["evidence_anchor"]) in normalized(hit["text"])
            for source in matching
        ):
            anchor_rank = rank
    return {"first_source_page_rank": page_rank, "first_anchor_rank": anchor_rank}


def summarize(rows, top_k, *, full_ranking=False):
    if not rows:
        raise ValueError("Cannot summarize an empty evaluation")
    # One evidence unit per question; a hit beyond K contributes only to full MRR.
    metrics = {
        **{f"source_page_hit_at_{k}": sum(
            row["first_source_page_rank"] is not None
            and row["first_source_page_rank"] <= k for row in rows) / len(rows)
           for k in (1, 3, 5)},
        **{f"anchor_hit_at_{k}": sum(
            row["first_anchor_rank"] is not None
            and row["first_anchor_rank"] <= k for row in rows) / len(rows)
           for k in (1, 3, 5)},
        f"anchor_mrr_at_{top_k}": sum(
            1 / row["first_anchor_rank"]
            if row["first_anchor_rank"] and row["first_anchor_rank"] <= top_k else 0
            for row in rows) / len(rows),
    }
    if full_ranking:
        metrics["mrr"] = sum(1 / row["first_anchor_rank"] if row["first_anchor_rank"] else 0
                             for row in rows) / len(rows)
        metrics["source_page_mrr"] = sum(
            1 / row["first_source_page_rank"] if row["first_source_page_rank"] else 0
            for row in rows) / len(rows)
    return metrics


def request_json(url, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=payload, headers={
        "Accept": "application/json", "Content-Type": "application/json",
    })
    with urlopen(request, timeout=90) as response:
        return json.load(response)


def check_hits(hits, allowed_documents, top_k):
    if not isinstance(hits, list) or len(hits) > top_k:
        raise ValueError("Invalid search result list")
    ids = []
    for hit in hits:
        if (type(hit["chunk_id"]) is not int
                or type(hit["document_id"]) is not int
                or hit["document_id"] not in allowed_documents
                or allowed_documents[hit["document_id"]] != hit["document_name"]
                or not isinstance(hit["text"], str)
                or not hit["text"].strip()
                or (hit["page_number"] is not None and (
                    type(hit["page_number"]) is not int or hit["page_number"] < 1))
                or isinstance(hit["score"], bool)
                or not isinstance(hit["score"], (float, int))
                or not math.isfinite(hit["score"])):
            raise ValueError("Invalid or out-of-course search result")
        ids.append(hit["chunk_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate canonical chunks in search response")
    if any(a["score"] < b["score"] for a, b in zip(hits, hits[1:])):
        raise ValueError("Results are not in descending similarity order")


def _corpus_signatures(items, *, hits=False):
    return Counter((item["document_name"], item["page_number"],
                    hashlib.sha256(item["text"].encode()).hexdigest() if hits
                    else item["text_sha256"]) for item in items)


def run(fixture, api_url, course_id, top_k, fetch=request_json, *,
        chunk_manifest=None, embedding_record=None):
    """CLI supplies a verified manifest; no manifest retains the old bounded diagnostic."""
    api_url = api_url.rstrip("/")
    full = chunk_manifest is not None
    # Probe one extra slot: asking for exactly N could hide an unexpected tail.
    retrieval_top_k = max(top_k, len(chunk_manifest) + 1) if full else top_k
    record = {
        "dataset_id": fixture["id"],
        "dataset_sha256": hashlib.sha256(json.dumps(
            fixture, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "source_pdf_sha256": {doc["name"]: doc["sha256"] for doc in fixture["documents"]},
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "course_id": course_id, "top_k": top_k,
        "retrieval_top_k": retrieval_top_k, "ranking_complete": False,
        "chunk_manifest": chunk_manifest, "embedding": None,
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "latency_scope": ("HTTP full-course search including query embedding and SQL; excludes backfill"
                          if full else "HTTP bounded search including query embedding and SQL; excludes backfill"),
        "status": "blocked", "search_quality_measured": False,
        "metrics": None, "results": [],
        "grading_note": "Page and short-anchor checks are diagnostics; manually review answer-bearing passages.",
    }
    try:
        if full and (not chunk_manifest or not 5 <= top_k <= 50 or retrieval_top_k > 50):
            raise ValueError("Full ranking requires 1–49 verified chunks plus an extra probe slot (API cap 50)")
        if full or embedding_record is not None:
            record["embedding"] = validate_embedding_record(embedding_record)
        expected_signatures = _corpus_signatures(chunk_manifest) if full else None
        canonical_ids = None
        course = fetch(f"{api_url}/courses/{course_id}")
        expected = {doc["name"] for doc in fixture["documents"]}
        documents = course["documents"]
        if ({doc["name"] for doc in documents} != expected
                or len(documents) != len(expected)):
            raise ValueError("Use a dedicated Course containing exactly the five named benchmark PDFs")
        if any(doc["status"] != "ready" for doc in documents):
            raise ValueError("All five PDFs must be parsed and ready before retrieval measurement")
        allowed = {doc["id"]: doc["name"] for doc in documents}
        for case in fixture["questions"]:
            start = time.perf_counter()
            response = fetch(f"{api_url}/courses/{course_id}/search",
                             {"query": case["question"], "top_k": retrieval_top_k})
            latency_ms = (time.perf_counter() - start) * 1000
            hits = response["results"]
            check_hits(hits, allowed, retrieval_top_k)
            if not hits:
                raise ValueError("Search returned no eligible chunks; check embedding backfill/configuration")
            if full:
                if _corpus_signatures(hits, hits=True) != expected_signatures:
                    raise ValueError("Search corpus differs from verified PDFs or embeddings are incomplete")
                ids = {hit["chunk_id"] for hit in hits}
                if canonical_ids is not None and ids != canonical_ids:
                    raise ValueError("Canonical chunks changed during evaluation")
                canonical_ids = ids
            record["results"].append({
                "id": case["id"], "query": case["question"],
                "expected_sources": golden_sources(case), **grade(case, hits),
                "latency_ms": latency_ms, "hits": hits,
            })
    except HTTPError as exc:
        record["blocker"] = f"API returned HTTP {exc.code}; check the service before measuring quality"
    except (URLError, TimeoutError, OSError):
        record["blocker"] = "API could not be reached or timed out"
    except (ValueError, KeyError, TypeError) as exc:
        record["blocker"] = str(exc)
    else:
        record.update(status="completed", search_quality_measured=True, ranking_complete=full,
                      metrics=summarize(record["results"], top_k, full_ranking=full))
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "run"])
    parser.add_argument("--pdf-dir", type=Path, default=DATASET.with_name("sources"))
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--course-id", type=int)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--embedding-record", type=Path,
                        help="Explicit model declaration or local runtime receipt; never an API key")
    args = parser.parse_args(argv)
    if args.command == "run" and (not args.course_id or args.course_id < 1 or not args.output):
        parser.error("run requires a positive --course-id and --output")
    if not 5 <= args.top_k <= 50:
        parser.error("--top-k must be between 5 and 50 (for Hit@1/3/5)")
    if args.command == "run" and not args.embedding_record:
        parser.error("run requires --embedding-record; model identity must not be inferred")
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new run filename")
    fixture = load_dataset()
    # Check unchanged original PDFs before any endpoint call.
    try:
        embedding = load_embedding_record(args.embedding_record) if args.command == "run" else None
        validation = validate_sources(fixture, args.pdf_dir)
    except (OSError, ValueError) as exc:
        print(f"Evaluation preflight failed: {exc}", file=sys.stderr)
        return 2
    record = {
        **validation, "dataset_id": fixture["id"],
        "dataset_sha256": hashlib.sha256(json.dumps(
            fixture, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_pdf_sha256": {doc["name"]: doc["sha256"] for doc in fixture["documents"]},
    } if args.command == "validate" else run(
        fixture, args.api_url, args.course_id, args.top_k,
        chunk_manifest=validation["chunk_manifest"], embedding_record=embedding)
    value = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(value)
    # PDF text includes ligatures etc. that a GBK/cp1252 Windows console cannot encode.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(value)
    return 2 if record["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
