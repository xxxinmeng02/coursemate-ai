"""Real PostgreSQL fixtures, isolated from application schemas."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.chunk import Chunk
from app.models.content import Content


@pytest.fixture()
def sqlite_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_fks(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def seed_chunks():
    def seed(factory, *, texts=("Parallel speedup.", "TCP networking."),
             embedded=False, status="ready", config="openai:text-embedding-3-small:1536:v1"):
        with factory() as db:
            content = Content(content_hash=uuid.uuid4().hex * 2,
                              storage_key="internal/fixture.pdf",
                              file_type="application/pdf", status=status)
            db.add(content)
            db.flush()
            chunks = [Chunk(content_id=content.id, text=value, page_number=i + 1,
                            chunk_index=i,
                            embedding=([1.0] + [0.0] * 1535) if embedded else None,
                            embedding_config=config if embedded else None)
                      for i, value in enumerate(texts)]
            db.add_all(chunks)
            db.commit()
            return content.id, [chunk.id for chunk in chunks]
    return seed


@pytest.fixture()
def postgres_factory():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to run PostgreSQL integration checks")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("TEST_POSTGRES_URL must point to PostgreSQL")
    schema = f"retrieval_test_{uuid.uuid4().hex}"
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_engine = engine.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(scoped_engine)
        yield sessionmaker(bind=scoped_engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
