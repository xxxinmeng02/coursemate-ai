"""Storage and similarity behavior must execute on PostgreSQL/pgvector."""
import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import literal_column, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.chunk import Chunk
from app.models.content import Content


def wait_for_lock(factory, pid):
    deadline = time.monotonic() + 5
    with factory() as observer:
        while time.monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            if observer.scalar(text(
                "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
            ), {"pid": pid}):
                return
            threading.Event().wait(0.01)
    pytest.fail("Competing writer did not wait for the Content lock")


@pytest.fixture()
def ready_content_id(postgres_factory):
    with postgres_factory() as db:
        content = Content(content_hash="a" * 64, storage_key="internal/a.pdf",
                          file_type="application/pdf", status="ready")
        db.add(content)
        db.commit()
        return content.id


def test_embedding_round_trip(postgres_factory, ready_content_id):
    vector = [1.0] + [0.0] * 1535
    with postgres_factory() as db:
        chunk = Chunk(content_id=ready_content_id, text="Parallel speedup.",
                      page_number=4, chunk_index=0)
        chunk.embedding = vector
        chunk.embedding_config = "openai:text-embedding-3-small:1536:v1"
        db.add(chunk)
        db.commit()
        chunk_id = chunk.id
    with postgres_factory() as db:
        restored = db.get(Chunk, chunk_id)
        assert list(restored.embedding) == vector
        assert restored.embedding_config == "openai:text-embedding-3-small:1536:v1"
        assert (restored.text, restored.page_number, restored.chunk_index) == (
            "Parallel speedup.", 4, 0)


def test_vector_dimension_enforced(postgres_factory, ready_content_id):
    with postgres_factory() as db:
        chunk = Chunk(content_id=ready_content_id, text="Bad dimension.", chunk_index=0)
        chunk.embedding = [1.0] + [0.0] * 1535
        chunk.embedding_config = "openai:text-embedding-3-small:1536:v1"
        db.add(chunk)
        db.commit()
        with pytest.raises(DBAPIError) as error:
            db.execute(update(Chunk).values(embedding=literal_column("'[1,0,0]'::vector")))
        assert error.value.orig.sqlstate == "22000"


@pytest.mark.parametrize("vector,config", [
    ([1.0] + [0.0] * 1535, None),
    (None, "openai:text-embedding-3-small:1536:v1"),
])
def test_embedding_pair_constraint(postgres_factory, ready_content_id, vector, config):
    with postgres_factory() as db:
        chunk = Chunk(content_id=ready_content_id, text="Incomplete pair.", chunk_index=0)
        chunk.embedding = vector
        chunk.embedding_config = config
        db.add(chunk)
        with pytest.raises(IntegrityError):
            db.commit()


def test_unembedded_chunk_is_preserved(postgres_factory, ready_content_id):
    with postgres_factory() as db:
        db.add(Chunk(content_id=ready_content_id, text="Not embedded yet.", chunk_index=0))
        db.commit()
    with postgres_factory() as db:
        chunk = db.scalar(select(Chunk))
        assert chunk.embedding is None
        assert chunk.embedding_config is None


def test_generation_attempts_serialize(postgres_factory, seed_chunks, monkeypatch):
    from app import embeddings
    from app.embedding_backfill import embed_content
    content_id, _ = seed_chunks(postgres_factory, texts=("Canonical text.",))
    entered, release, contender_started = threading.Event(), threading.Event(), threading.Event()
    contender_pid = []

    def provider(value, **kw):
        entered.set()
        assert release.wait(10)
        return [1.0] + [0.0] * 1535

    monkeypatch.setattr(embeddings, "embed_text", provider)

    def generate(*, contender=False):
        with postgres_factory() as db:
            if contender:
                contender_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                contender_started.set()
            return embed_content(db, content_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(generate)
        assert entered.wait(10)
        contender = pool.submit(generate, contender=True)
        try:
            assert contender_started.wait(10)
            wait_for_lock(postgres_factory, contender_pid[0])
            with postgres_factory() as observer:
                assert observer.scalar(select(Chunk.embedding)) is None
        finally:
            release.set()
        assert owner.result(timeout=10) == {"generated": 1, "skipped": 0}
        assert contender.result(timeout=10) == {"generated": 0, "skipped": 1}


@pytest.mark.parametrize("refresh_first", [False, True])
def test_generation_serializes_with_pdf_refresh(
    postgres_factory, seed_chunks, monkeypatch, refresh_first,
):
    from app import embeddings
    from app.embedding_backfill import embed_content
    from app.parsing import process_content
    content_id, _ = seed_chunks(postgres_factory, texts=("Old text.",))
    entered, release, contender_started = threading.Event(), threading.Event(), threading.Event()
    contender_pid = []

    def extract(path):
        if refresh_first:
            entered.set()
            assert release.wait(10)
        return ["Fresh text."]

    def provider(value, **kw):
        if not refresh_first:
            entered.set()
            assert release.wait(10)
        else:
            assert value == "Fresh text."  # Never embed the stale pre-refresh text.
        return [1.0] + [0.0] * 1535

    monkeypatch.setattr("app.parsing.extract_pdf_pages", extract)
    monkeypatch.setattr(embeddings, "embed_text", provider)

    def execute(refresh, *, contender=False):
        with postgres_factory() as db:
            content = db.get(Content, content_id)
            if contender:
                contender_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                contender_started.set()
            if refresh:
                process_content(db, content)
            else:
                embed_content(db, content_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(execute, refresh_first)
        assert entered.wait(10)
        contender = pool.submit(execute, not refresh_first, contender=True)
        try:
            assert contender_started.wait(10)
            wait_for_lock(postgres_factory, contender_pid[0])
        finally:
            release.set()
        owner.result(timeout=10)
        contender.result(timeout=10)
    with postgres_factory() as db:
        chunks = db.scalars(select(Chunk)).all()
        assert len(chunks) == 1
        assert chunks[0].text == "Fresh text."
        assert (chunks[0].embedding is not None) == refresh_first
