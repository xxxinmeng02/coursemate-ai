import pytest
from sqlalchemy import event, select

from app import embeddings
from app.models.chunk import Chunk
from app.models.content import Content
from app.models.course import Course


@pytest.fixture(params=["sqlite_factory", "postgres_factory"])
def db_factory(request):
    return request.getfixturevalue(request.param)


def snapshot(factory, content_id):
    with factory() as db:
        content = db.get(Content, content_id)
        rows = db.scalars(select(Chunk).where(Chunk.content_id == content_id)
                          .order_by(Chunk.chunk_index)).all()
        return content.status, [
            (c.id, c.text, c.page_number, c.chunk_index,
             list(c.embedding) if c.embedding is not None else None, c.embedding_config)
            for c in rows]


def test_generation_persists_and_retry_skips_provider(db_factory, seed_chunks, monkeypatch):
    from app.embedding_backfill import embed_content
    content_id, chunk_ids = seed_chunks(db_factory)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: [1.0] + [0.0] * 1535)
    with db_factory() as db:
        assert embed_content(db, content_id) == {"generated": 2, "skipped": 0}
    state, rows = snapshot(db_factory, content_id)
    assert state == "ready"
    assert [row[0] for row in rows] == chunk_ids
    assert [row[1:4] for row in rows] == [("Parallel speedup.", 1, 0), ("TCP networking.", 2, 1)]
    assert all(row[4] == [1.0] + [0.0] * 1535 for row in rows)
    assert all(row[5] == "openai:text-embedding-3-small:1536:v1" for row in rows)

    def unexpected(*args, **kwargs):
        pytest.fail("Valid embeddings must not be regenerated")

    monkeypatch.setattr(embeddings, "embed_text", unexpected)
    with db_factory() as db:
        assert embed_content(db, content_id) == {"generated": 0, "skipped": 2}


@pytest.mark.parametrize("force,revision", [(True, "v1"), (False, "v2")])
def test_force_and_configuration_change_replace_vectors(
    db_factory, seed_chunks, monkeypatch, force, revision,
):
    from app.embedding_backfill import embed_content
    content_id, chunk_ids = seed_chunks(db_factory, embedded=True)
    monkeypatch.setenv("EMBEDDING_REVISION", revision)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: [0.0, 1.0] + [0.0] * 1534)
    with db_factory() as db:
        assert embed_content(db, content_id, force=force)["generated"] == 2
    _, rows = snapshot(db_factory, content_id)
    assert [row[0] for row in rows] == chunk_ids
    assert all(row[4] == [0.0, 1.0] + [0.0] * 1534 for row in rows)
    assert all(row[5] == f"openai:text-embedding-3-small:1536:{revision}" for row in rows)


def test_later_provider_failure_preserves_all_existing_data(db_factory, seed_chunks, monkeypatch):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory, embedded=True)
    before = snapshot(db_factory, content_id)
    count = 0

    def embed(text, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise embeddings.EmbeddingError("Provider unavailable")
        return [0.0, 1.0] + [0.0] * 1534

    monkeypatch.setattr(embeddings, "embed_text", embed)
    with db_factory() as db:
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id, force=True)
    assert snapshot(db_factory, content_id) == before


def test_invalid_vector_preserves_chunks(db_factory, seed_chunks, monkeypatch):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory)
    before = snapshot(db_factory, content_id)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: [0.0] * 1536)
    with db_factory() as db:
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id)
    assert snapshot(db_factory, content_id) == before


@pytest.mark.parametrize("status", ["uploaded", "processing", "failed", "pending_cleanup"])
def test_nonready_content_is_not_mutated(db_factory, seed_chunks, status):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory, status=status)
    before = snapshot(db_factory, content_id)
    with db_factory() as db:
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id)
    assert snapshot(db_factory, content_id) == before


def test_missing_content(db_factory):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    with db_factory() as db:
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, 999999)


def test_generation_does_not_commit_pending_writes(db_factory, seed_chunks):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory)
    with db_factory() as db:
        db.add(Course(name="Unrelated pending write"))
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id)
        assert db.new  # Caller state is not discarded on a precondition error.
    with db_factory() as db:
        assert db.scalar(select(Course)) is None


def test_generation_rejects_caller_savepoint(db_factory, seed_chunks):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory)
    with db_factory() as db, db.begin_nested():
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id)
        assert db.in_nested_transaction()


def test_commit_failure_does_not_perform_second_cleanup(db_factory, seed_chunks, monkeypatch):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory, embedded=True)
    before = snapshot(db_factory, content_id)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: [0.0, 1.0] + [0.0] * 1534)
    with db_factory() as db:
        commits = []
        original = db.commit

        def fail_first():
            commits.append(1)
            if len(commits) == 1:
                raise RuntimeError("Commit failed")
            original()

        monkeypatch.setattr(db, "commit", fail_first)
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id, force=True)
        assert len(commits) == 1
    assert snapshot(db_factory, content_id) == before


def test_flush_failure_preserves_embeddings(db_factory, seed_chunks, monkeypatch):
    from app.embedding_backfill import EmbeddingGenerationError, embed_content
    content_id, _ = seed_chunks(db_factory, embedded=True)
    before = snapshot(db_factory, content_id)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: [0.0, 1.0] + [0.0] * 1534)
    with db_factory() as db:
        def fail_flush(*args):
            raise RuntimeError("Persistence failed")
        event.listen(db, "after_flush", fail_flush)
        with pytest.raises(EmbeddingGenerationError):
            embed_content(db, content_id, force=True)
    assert snapshot(db_factory, content_id) == before


def test_generation_captures_one_configuration(db_factory, seed_chunks, monkeypatch):
    from app.embedding_backfill import embed_content
    content_id, _ = seed_chunks(db_factory)
    configs = []

    def embed(text, *, config):
        configs.append(config.identifier)
        monkeypatch.setenv("EMBEDDING_REVISION", "changed-mid-operation")
        return [1.0] + [0.0] * 1535

    monkeypatch.setattr(embeddings, "embed_text", embed)
    with db_factory() as db:
        embed_content(db, content_id)
    _, rows = snapshot(db_factory, content_id)
    assert configs == ["openai:text-embedding-3-small:1536:v1"] * 2
    assert all(row[5] == configs[0] for row in rows)


def test_cli_reports_failure_but_keeps_completed_content(db_factory, seed_chunks, monkeypatch, capsys):
    from app import embedding_backfill
    first_id, _ = seed_chunks(db_factory, texts=("Good content.",))
    failed_id, _ = seed_chunks(db_factory, texts=("Fail content.",))
    monkeypatch.setattr(embedding_backfill, "get_session_factory", lambda: db_factory)

    def embed(text, **kw):
        if text == "Fail content.":
            raise embeddings.EmbeddingError("Unusable provider")
        return [1.0] + [0.0] * 1535

    monkeypatch.setattr(embeddings, "embed_text", embed)
    assert embedding_backfill.main([]) == 1
    assert snapshot(db_factory, first_id)[1][0][4] is not None
    assert snapshot(db_factory, failed_id)[1][0][4] is None
    assert "failed=1" in capsys.readouterr().out


def test_cli_selected_content_is_idempotent(db_factory, seed_chunks, monkeypatch):
    from app import embedding_backfill
    content_id, _ = seed_chunks(db_factory)
    monkeypatch.setattr(embedding_backfill, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(embeddings, "embed_text", lambda text, **kw: [1.0] + [0.0] * 1535)
    assert embedding_backfill.main(["--content-id", str(content_id)]) == 0
    assert embedding_backfill.main(["--content-id", str(content_id)]) == 0
