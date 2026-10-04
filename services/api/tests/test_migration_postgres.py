"""Upgrade the actual Alembic chain in a private PostgreSQL schema."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_postgres_upgrade_refuses_duplicates_then_enforces_constraint():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL for migration checks")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        pytest.fail("TEST_POSTGRES_URL must be PostgreSQL")
    schema = "migration_test_" + uuid.uuid4().hex
    with engine.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped_engine = create_engine(scoped_url)
    env = dict(os.environ, DATABASE_URL=scoped_url.render_as_string(hide_password=False))
    def migrate(target):
        return subprocess.run([sys.executable, "-m", "alembic", "upgrade", target],
                              cwd=Path(__file__).resolve().parents[1], env=env,
                              capture_output=True, text=True, timeout=30)
    try:
        assert migrate("9a2f1c0e4b7d").returncode == 0
        with scoped_engine.begin() as db:
            db.execute(text("INSERT INTO courses(name) VALUES ('Upgrade course')"))
            db.execute(text("INSERT INTO contents(content_hash,storage_key,file_type,status) VALUES (:hash,'storage/a.pdf','application/pdf','uploaded')"), {"hash":"a"*64})
            db.execute(text("INSERT INTO documents(course_id,content_id,name) VALUES (1,1,'first.pdf'),(1,1,'duplicate.pdf')"))
        failure = migrate("head")
        assert failure.returncode != 0
        assert "explicitly reconcile" in failure.stderr
        with scoped_engine.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "9a2f1c0e4b7d"
            assert db.scalar(text("SELECT COUNT(*) FROM documents")) == 2
            db.execute(text("DELETE FROM documents WHERE name='duplicate.pdf'"))
        assert migrate("head").returncode == 0
        with scoped_engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "c3a11d0c2026"
            assert db.scalar(text("SELECT COUNT(*) FROM pg_constraint WHERE conname='uq_documents_course_content' AND conrelid='documents'::regclass")) == 1
    finally:
        scoped_engine.dispose()
        with engine.begin() as db:
            db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
