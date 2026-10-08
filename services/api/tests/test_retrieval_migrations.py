"""Upgrade the existing head with real pre-retrieval rows, then round-trip."""
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_upgrade_existing_head_preserves_chunks_and_round_trips():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL for Alembic/pgvector integration")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("TEST_POSTGRES_URL must use PostgreSQL")
    schema = f"retrieval_migration_{uuid.uuid4().hex}"
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema},public"})
    scoped = create_engine(scoped_url)
    env = dict(os.environ, DATABASE_URL=scoped_url.render_as_string(hide_password=False))

    def alembic(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", *args], env=env,
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        alembic("upgrade", "9a2f1c0e4b7d")
        with scoped.begin() as conn:
            course_id = conn.scalar(text("INSERT INTO courses (name) VALUES ('Existing Course') RETURNING id"))
            content_id = conn.scalar(text(
                "INSERT INTO contents (content_hash, storage_key, file_type, status) "
                "VALUES ('old-hash', 'internal/old.pdf', 'application/pdf', 'ready') RETURNING id"))
            conn.execute(text("INSERT INTO documents (course_id, content_id, name) VALUES (:course, :content, 'old.pdf')"),
                         {"course": course_id, "content": content_id})
            conn.execute(text("INSERT INTO chunks (content_id, text, page_number, chunk_index) "
                              "VALUES (:content, 'Existing canonical text', 5, 0)"), {"content": content_id})
        alembic("upgrade", "head")
        with scoped.connect() as conn:
            row = conn.execute(text("SELECT text, page_number, chunk_index, embedding, embedding_config FROM chunks")).one()
            assert tuple(row) == ("Existing canonical text", 5, 0, None, None)
            assert conn.scalar(text("SELECT status FROM contents")) == "ready"
            assert tuple(conn.execute(text(
                "SELECT course_id, content_id, name FROM documents"
            )).one()) == (course_id, content_id, "old.pdf")
            assert conn.scalar(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                                    "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'")) == "vector(1536)"
            assert conn.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 1
        assert "c81d4a6b209f (head)" in alembic("heads")
        assert "c81d4a6b209f" in alembic("current")
        assert "No new upgrade operations detected" in alembic("check")
        alembic("downgrade", "9a2f1c0e4b7d")
        with scoped.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM chunks")) == 1
            assert conn.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 1
        alembic("upgrade", "head")
        with scoped.connect() as conn:
            assert conn.scalar(text("SELECT text FROM chunks")) == "Existing canonical text"
            assert tuple(conn.execute(text(
                "SELECT course_id, content_id, name FROM documents"
            )).one()) == (course_id, content_id, "old.pdf")
    finally:
        scoped.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
