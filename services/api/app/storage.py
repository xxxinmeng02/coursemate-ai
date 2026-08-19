from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import UploadFile

STORAGE_DIR = Path(__file__).resolve().parents[1] / "storage"
STORAGE_KEY_PREFIX = "storage"
MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"


class InvalidPdfError(ValueError):
    """Raised when an upload does not pass the PDF checks."""


class DocumentTooLargeError(ValueError):
    """Raised when an upload exceeds MAX_DOCUMENT_SIZE_BYTES."""


@dataclass(frozen=True)
class StagedUpload:
    """A validated upload stored in a temporary path until DB commit."""

    path: Path
    content_hash: str


def storage_path_for_hash(content_hash: str) -> Path:
    """Return the hash-derived filesystem path for a PDF."""
    return STORAGE_DIR / f"{content_hash}.pdf"


def storage_key_for_hash(content_hash: str) -> str:
    """Return the stable, database-safe key for a stored PDF."""
    return f"{STORAGE_KEY_PREFIX}/{content_hash}.pdf"


async def stage_pdf_upload(upload: UploadFile) -> StagedUpload:
    """Validate and stream a PDF upload into a temporary storage file."""
    filename = upload.filename or ""
    content_type = (upload.content_type or "").split(";", 1)[0].lower()

    if not filename.lower().endswith(".pdf") or content_type != "application/pdf":
        raise InvalidPdfError("Only PDF files are accepted")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            dir=STORAGE_DIR,
            prefix=".upload-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            digest = hashlib.sha256()
            total_size = 0
            signature_bytes = bytearray()

            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break

                total_size += len(chunk)
                if total_size > MAX_DOCUMENT_SIZE_BYTES:
                    raise DocumentTooLargeError(
                        f"Document exceeds the {MAX_DOCUMENT_SIZE_BYTES} byte limit"
                    )

                if len(signature_bytes) < len(PDF_SIGNATURE):
                    signature_bytes.extend(
                        chunk[: len(PDF_SIGNATURE) - len(signature_bytes)]
                    )
                digest.update(chunk)
                temporary_file.write(chunk)

            if not bytes(signature_bytes).startswith(PDF_SIGNATURE):
                raise InvalidPdfError("File does not have a valid PDF signature")

        return StagedUpload(path=temporary_path, content_hash=digest.hexdigest())
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def promote_staged_upload(staged: StagedUpload) -> tuple[Path, bool]:
    """Atomically link a staged file to its hash-derived final path.

    The boolean indicates whether this request created the final file and may
    therefore clean it up if its database transaction fails.
    """
    final_path = storage_path_for_hash(staged.content_hash)
    try:
        os.link(staged.path, final_path)
    except FileExistsError:
        staged.path.unlink(missing_ok=True)
        return final_path, False

    staged.path.unlink(missing_ok=True)
    return final_path, True


def discard_staged_upload(staged: StagedUpload | None) -> None:
    """Remove a temporary upload if it still exists."""
    if staged is not None:
        staged.path.unlink(missing_ok=True)


def cleanup_owned_file(path: Path | None, owned_by_request: bool) -> None:
    """Remove a final file only when this request created it."""
    if path is not None and owned_by_request:
        path.unlink(missing_ok=True)
