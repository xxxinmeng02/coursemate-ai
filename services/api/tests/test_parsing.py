from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import storage
import app.models  # noqa: F401  # register all models on Base.metadata
from app.database import Base
from app.models.chunk import Chunk
from app.models.content import Content
from app.models.course import Course
from app.parsing import (
    ContentProcessingError,
    chunk_page,
    normalize_text,
    process_content,
)


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def storage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    return tmp_path


def _pdf_bytes(page_texts: list[str]) -> bytes:
    writer = PdfWriter()
    for page_text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        if page_text:
            escaped = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode())
            page[NameObject("/Contents")] = stream

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _create_content(
    session: Session,
    storage_dir,
    page_texts: list[str],
    content_hash: str | None = None,
) -> Content:
    pdf_bytes = _pdf_bytes(page_texts)
    content_hash = content_hash or hashlib.sha256(pdf_bytes).hexdigest()
    path = storage_dir / f"{content_hash}.pdf"
    path.write_bytes(pdf_bytes)
    content = Content(
        content_hash=content_hash,
        storage_key=f"storage/{content_hash}.pdf",
        file_type="application/pdf",
        status="uploaded",
    )
    session.add(content)
    session.commit()
    return content


def test_process_content_extracts_short_pdf(db_session_factory, storage_dir):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["Short page text."])

        process_content(session, content)

        chunks = session.query(Chunk).order_by(Chunk.chunk_index).all()
        assert content.status == "ready"
        assert [(chunk.page_number, chunk.chunk_index) for chunk in chunks] == [(1, 0)]
        assert "Short page text." in chunks[0].text


def test_process_content_keeps_pages_separate_and_indexes_globally(
    db_session_factory,
    storage_dir,
):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["First page.", "Second page."])

        process_content(session, content)

        chunks = session.query(Chunk).order_by(Chunk.chunk_index).all()
        assert [chunk.page_number for chunk in chunks] == [1, 2]
        assert [chunk.chunk_index for chunk in chunks] == [0, 1]
        assert "First page." in chunks[0].text
        assert "Second page." in chunks[1].text
        assert "Second page." not in chunks[0].text


def test_normalize_text_preserves_paragraph_boundaries_and_cleans_whitespace():
    raw = "  first  line\r\n\r\n second\t\tline\n\n\n third  "

    assert normalize_text(raw) == "first line\n\nsecond line\n\nthird"


def test_chunk_page_prefers_paragraph_boundary_and_keeps_overlap():
    first_paragraph = "A" * 1090 + "."
    second_paragraph = "B" * 1090 + "."
    third_paragraph = "C" * 300 + "."
    text = "\n\n".join([first_paragraph, second_paragraph, third_paragraph])

    chunks = chunk_page(text)

    assert len(chunks) == 3
    assert chunks[0].endswith(".")
    assert first_paragraph[-100:] in chunks[1]
    assert all(900 <= len(chunk) <= 1400 for chunk in chunks[:2])


def test_empty_pdf_fails_without_empty_chunks(db_session_factory, storage_dir):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, [""])

        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        assert content.status == "failed"
        assert session.query(Chunk).count() == 0


def test_corrupt_pdf_fails_without_partial_chunks(
    db_session_factory,
    storage_dir,
):
    corrupt_hash = "c" * 64
    (storage_dir / f"{corrupt_hash}.pdf").write_bytes(b"%PDF-1.7\nnot a complete pdf")
    with db_session_factory() as session:
        content = Content(
            content_hash=corrupt_hash,
            storage_key=f"storage/{corrupt_hash}.pdf",
            file_type="application/pdf",
            status="uploaded",
        )
        session.add(content)
        session.commit()

        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        assert content.status == "failed"
        assert session.query(Chunk).count() == 0


def test_retry_replaces_stale_chunks_instead_of_duplicating(
    db_session_factory,
    storage_dir,
):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["Fresh text."])
        session.add(
            Chunk(
                content_id=content.id,
                text="stale text",
                page_number=99,
                chunk_index=0,
            )
        )
        content.status = "ready"
        session.commit()

        process_content(session, content)

        chunks = session.query(Chunk).all()
        assert len(chunks) == 1
        assert chunks[0].text == "Fresh text."
        assert chunks[0].page_number == 1
        assert chunks[0].chunk_index == 0
        assert content.status == "ready"


def test_chunk_persistence_failure_marks_content_failed_and_cleans_chunks(
    db_session_factory,
    storage_dir,
    monkeypatch,
):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["Persist me."])
        def fail_chunk_insert(current_session, flush_context):
            if any(isinstance(item, Chunk) for item in current_session.new):
                raise RuntimeError("simulated chunk persistence failure")

        event.listen(session, "after_flush", fail_chunk_insert)

        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        assert content.status == "failed"
        assert session.query(Chunk).count() == 0


def _ready_content(session, storage_dir):
    content = _create_content(session, storage_dir, ["Replacement page one.", "Replacement page two."])
    content.status = "ready"
    session.add(Chunk(content_id=content.id, text="Original usable text.", page_number=7, chunk_index=0))
    session.commit()
    return content


def _chunk_snapshot(session, content_id):
    return list(session.execute(
        select(Chunk.text, Chunk.page_number, Chunk.chunk_index)
        .where(Chunk.content_id == content_id).order_by(Chunk.chunk_index)
    ).all())


def test_failed_refresh_preserves_ready_chunks(db_session_factory, storage_dir, monkeypatch):
    with db_session_factory() as session:
        content = _ready_content(session, storage_dir)

        def fail_extraction(path):
            raise RuntimeError("refresh extraction failed")

        monkeypatch.setattr("app.parsing.extract_pdf_pages", fail_extraction)
        with pytest.raises(ContentProcessingError) as error:
            process_content(session, content)

        assert isinstance(error.value.__cause__, RuntimeError)
        session.expire_all()
        assert content.status == "ready"
        assert _chunk_snapshot(session, content.id) == [("Original usable text.", 7, 0)]


def test_successful_refresh_replaces_complete_canonical_set(db_session_factory, storage_dir):
    with db_session_factory() as session:
        content = _ready_content(session, storage_dir)
        chunks = process_content(session, content)

        session.expire_all()
        assert content.status == "ready"
        assert len(chunks) == 2
        assert _chunk_snapshot(session, content.id) == [
            ("Replacement page one.", 1, 0), ("Replacement page two.", 2, 1),
        ]


def test_failed_replacement_rolls_back_old_chunks(db_session_factory, storage_dir):
    with db_session_factory() as session:
        content = _ready_content(session, storage_dir)

        def fail_after_insert(current_session, flush_context):
            if any(isinstance(item, Chunk) for item in current_session.new):
                raise RuntimeError("failure after an actual replacement INSERT")

        event.listen(session, "after_flush", fail_after_insert)
        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        session.expire_all()
        assert content.status == "ready"
        assert _chunk_snapshot(session, content.id) == [("Original usable text.", 7, 0)]


def test_stale_failed_attempt_preserves_latest_success(db_session_factory, storage_dir, monkeypatch):
    with db_session_factory() as seed:
        content_id = _create_content(seed, storage_dir, ["Newest successful text."]).id

    with db_session_factory() as stale, db_session_factory() as winner:
        stale_content = stale.get(Content, content_id)
        process_content(winner, winner.get(Content, content_id))

        def fail_stale_extraction(path):
            raise RuntimeError("stale attempt fails")

        monkeypatch.setattr("app.parsing.extract_pdf_pages", fail_stale_extraction)
        with pytest.raises(ContentProcessingError):
            process_content(stale, stale_content)

    with db_session_factory() as check:
        assert check.get(Content, content_id).status == "ready"
        assert _chunk_snapshot(check, content_id) == [("Newest successful text.", 1, 0)]


def test_competing_connection_cannot_extract_while_owner_is_active(tmp_path, storage_dir, monkeypatch):
    # Separate physical connections are essential: StaticPool is not a concurrency test.
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"timeout": 0})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as seed:
            content_id = _create_content(seed, storage_dir, ["Owner result."]).id
        with factory() as owner, factory() as contender:
            owner_content = owner.get(Content, content_id)
            contender_content = contender.get(Content, content_id)
            attempted = False

            def extract_while_contending(path):
                nonlocal attempted
                if not attempted:
                    attempted = True
                    with pytest.raises(ContentProcessingError):
                        process_content(contender, contender_content)
                return ["Owner result."]

            monkeypatch.setattr("app.parsing.extract_pdf_pages", extract_while_contending)
            process_content(owner, owner_content)
        with factory() as check:
            assert check.get(Content, content_id).status == "ready"
            assert _chunk_snapshot(check, content_id) == [("Owner result.", 1, 0)]
    finally:
        engine.dispose()


def test_final_commit_failure_preserves_previous_data(db_session_factory, storage_dir, monkeypatch):
    with db_session_factory() as session:
        content = _ready_content(session, storage_dir)
        content_id = content.id
        real_commit = session.commit
        commit_attempts = 0

        def fail_commit():
            nonlocal commit_attempts
            commit_attempts += 1
            if commit_attempts == 1:
                raise RuntimeError("final commit failed before reaching the database")
            # Unsafe cleanup followed by a second commit must really persist,
            # so it cannot hide behind an always-failing commit stub.
            return real_commit()

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(ContentProcessingError):
            process_content(session, content)
        assert commit_attempts == 1

    with db_session_factory() as check:
        assert check.get(Content, content_id).status == "ready"
        assert _chunk_snapshot(check, content_id) == [("Original usable text.", 7, 0)]


@pytest.mark.parametrize("status", ["processing", "pending_cleanup"])
def test_ineligible_content_is_not_processed(db_session_factory, storage_dir, status):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["Must not be processed."])
        content.status = status
        session.commit()

        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        session.expire_all()
        assert content.status == status
        assert _chunk_snapshot(session, content.id) == []


def test_processing_does_not_commit_unrelated_pending_changes(db_session_factory, storage_dir):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["PDF text."])
        unrelated = Course(name="Uncommitted course")
        session.add(unrelated)

        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        assert unrelated in session.new
        session.rollback()
        assert session.query(Course).count() == 0
