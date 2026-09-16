from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import storage
import app.models  # noqa: F401  # register all models on Base.metadata
from app.database import Base
from app.models.chunk import Chunk
from app.models.content import Content
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
        session.commit()

        process_content(session, content)

        chunks = session.query(Chunk).all()
        assert len(chunks) == 1
        assert chunks[0].text == "Fresh text."
        assert chunks[0].page_number == 1
        assert chunks[0].chunk_index == 0


def test_chunk_persistence_failure_marks_content_failed_and_cleans_chunks(
    db_session_factory,
    storage_dir,
    monkeypatch,
):
    with db_session_factory() as session:
        content = _create_content(session, storage_dir, ["Persist me."])
        real_commit = Session.commit
        commit_calls = 0

        def fail_ready_commit(current_session):
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 2:
                raise RuntimeError("simulated chunk persistence failure")
            return real_commit(current_session)

        monkeypatch.setattr(Session, "commit", fail_ready_commit)

        with pytest.raises(ContentProcessingError):
            process_content(session, content)

        assert content.status == "failed"
        assert session.query(Chunk).count() == 0
