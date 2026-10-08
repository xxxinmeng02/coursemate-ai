"""Storage and similarity behavior must execute on PostgreSQL/pgvector."""
import pytest
from sqlalchemy import literal_column, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.chunk import Chunk
from app.models.content import Content


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
