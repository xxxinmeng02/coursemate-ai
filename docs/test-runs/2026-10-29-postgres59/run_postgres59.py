"""Reproduce this 59-case PostgreSQL run; never enables real embedding requests."""
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[2]
API = ROOT / "services/api"
URL = "postgresql+psycopg://retrieval_test:retrieval_test_local_only@127.0.0.1:55437/retrieval_test"
FILES = ["test_retrieval_postgres.py", "test_embedding_backfill.py", "test_retrieval_api.py",
         "test_processing_postgres.py", "test_retrieval_migrations.py", "test_retrieval_eval.py",
         "test_course_retrieval_eval.py"]
LIVE = {"test_live_model_topic_quality", "test_live_course_benchmark"}


def write_json(name, value):
    (RUN / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    if (RUN / "summary.json").exists() or (RUN / "junit.xml").exists():
        raise SystemExit("Evidence already exists; use a new run directory instead of overwriting it")
    # dotenv does not override these explicit settings. Never inherit a real key.
    os.environ.update(TEST_POSTGRES_URL=URL, DATABASE_URL=URL, OPENAI_API_KEY="",
                      RUN_LIVE_EMBEDDING_EVAL="0", PYTHONUNBUFFERED="1")
    os.chdir(API)
    import httpx
    import pytest
    from sqlalchemy import create_engine, text

    original_post = httpx.post
    blocked_requests = []
    def guarded_post(url, *args, **kwargs):
        if urlsplit(str(url)).hostname == "api.openai.com":
            blocked_requests.append("api.openai.com")
            raise AssertionError("Real embedding HTTP requests are forbidden in this test run")
        return original_post(url, *args, **kwargs)
    httpx.post = guarded_post

    class Selection:
        def pytest_collection_modifyitems(self, config, items):
            selected, deselected, excluded_live = [], [], []
            for item in items:
                name = getattr(item, "originalname", item.name)
                if name in LIVE:
                    excluded_live.append(item.nodeid)
                    deselected.append(item)
                    continue
                params = getattr(getattr(item, "callspec", None), "params", {})
                is_pg = ("postgres_factory" in item.fixturenames
                         or params.get("db_factory") == "postgres_factory"
                         or item.path.name == "test_retrieval_migrations.py")
                (selected if is_pg else deselected).append(item)
            write_json("selection.json", {
                "selected_count": len(selected), "selected": [item.nodeid for item in selected],
                "excluded_live": excluded_live,
                "other_deselected": [item.nodeid for item in deselected if item.nodeid not in excluded_live],
            })
            if len(selected) != 59 or len(excluded_live) != 2:
                raise pytest.UsageError("Expected exactly 59 PostgreSQL cases and two excluded live cases")
            config.hook.pytest_deselected(items=deselected)
            items[:] = selected

    engine = create_engine(URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        with engine.connect() as connection:
            database = {
                "server_version": connection.scalar(text("SHOW server_version")),
                "pgvector_version": connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")),
                "database": connection.scalar(text("SELECT current_database()")),
            }
    finally:
        engine.dispose()
    command = ["-vv", "-ra", "--tb=long", "--color=no", f"--junitxml={RUN / 'junit.xml'}",
               *[f"tests/{name}" for name in FILES]]
    metadata = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "worktree_has_local_changes": True, "working_directory": str(API),
        "python_executable": sys.executable, "python_version": platform.python_version(),
        "packages": {name: version(name) for name in ("pytest", "SQLAlchemy", "psycopg", "pgvector", "alembic", "httpx")},
        "database": database, "test_address": "127.0.0.1:55437/retrieval_test",
        "api_key_forced_empty": True, "live_eval_switch": "0",
        "pytest_arguments": command,
    }
    write_json("environment.json", metadata)
    source_files = sorted(set(ROOT.glob("services/api/app/**/*.py"))
                          | set(ROOT.glob("services/api/tests/*.py"))
                          | set(ROOT.glob("services/api/alembic/**/*.py")))
    write_json("source-sha256.json", {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in source_files})
    try:
        exit_code = int(pytest.main(command, plugins=[Selection()]))
    finally:
        httpx.post = original_post
    suites = ET.parse(RUN / "junit.xml").getroot()
    cases = list(suites.iter("testcase"))
    summary = {"finished_at_utc": datetime.now(timezone.utc).isoformat(), "exit_code": exit_code,
               "tests": len(cases), "failures": len(list(suites.iter("failure"))),
               "errors": len(list(suites.iter("error"))), "skipped": len(list(suites.iter("skipped"))),
               "openai_http_attempts_blocked": len(blocked_requests), "real_embeddings_used": False,
               "duration_seconds": sum(float(s.attrib.get("time", 0)) for s in suites.findall("testsuite"))}
    summary["passed"] = summary["tests"] - summary["failures"] - summary["errors"] - summary["skipped"]
    write_json("summary.json", summary)
    print("\nSaved run summary:", json.dumps(summary, ensure_ascii=False))
    if summary["tests"] != 59 or blocked_requests:
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
