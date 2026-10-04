import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import jobs, storage
from app.content_lifecycle import lock_content, lock_content_hash, lock_course, mark_unreferenced
from app.database import get_db
from app.models.content import Content
from app.models.course import Course
from app.models.document import Document
from app.schemas.course import DocumentSummary

router = APIRouter(prefix="/courses/{course_id}/documents", tags=["documents"])
logger = logging.getLogger(__name__)


def summary(document: Document, content: Content) -> DocumentSummary:
    return DocumentSummary(id=document.id, name=document.name, created_at=document.created_at, status=content.status)


def _scoped_document(db: Session, course_id: int, document_id: int) -> Document:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.course_id == course_id))
    if document is None:
        raise HTTPException(404, "Document not found in this course")
    return document


@router.post("", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
async def upload_document(course_id: int, background_tasks: BackgroundTasks,
                          file: UploadFile = File(...), db: Session = Depends(get_db)) -> DocumentSummary:
    staged = None
    final_path = None
    owns_file = committed = False
    try:
        if db.get(Course, course_id) is None:
            raise HTTPException(404, "Course not found")
        try:
            staged = await storage.stage_pdf_upload(file)
        except storage.DocumentTooLargeError as exc:
            raise HTTPException(413, str(exc)) from exc
        except storage.InvalidPdfError as exc:
            raise HTTPException(400, str(exc)) from exc

        if lock_course(db, course_id) is None:
            raise HTTPException(404, "Course not found")
        lock_content_hash(db, staged.content_hash)
        content = db.scalar(select(Content).where(Content.content_hash == staged.content_hash))
        if content is not None:
            content = lock_content(db, content.id)
            if content.status == "pending_cleanup":
                raise HTTPException(409, "Content is pending cleanup; retry upload after cleanup completes")
            if db.scalar(select(Document.id).where(Document.course_id == course_id, Document.content_id == content.id)) is not None:
                raise HTTPException(409, "This document is already attached to the course")
        else:
            content = Content(content_hash=staged.content_hash,
                              storage_key=storage.storage_key_for_hash(staged.content_hash),
                              file_type="application/pdf", status="uploaded")
            db.add(content)
            db.flush()
            final_path, owns_file = storage.promote_staged_upload(staged)
        document = Document(course_id=course_id, content_id=content.id, name=file.filename or "document.pdf")
        db.add(document)
        db.flush()
        result = summary(document, content)
        content_id = content.id
        db.commit()
        committed = True
        if result.status == "uploaded":
            jobs.schedule_content_processing(background_tasks, content_id)
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Document upload conflicted with another request; refresh and retry") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, "Could not save document") from exc
    finally:
        try:
            storage.discard_staged_upload(staged)
        except OSError:
            logger.exception("Could not discard staged upload; retaining temporary file")
        if owns_file and not committed and staged is not None:
            # Rollback releases the creation lock. Reacquire it before deleting:
            # a concurrent winner may have adopted the same hash path meanwhile.
            try:
                lock_content_hash(db, staged.content_hash)
                if db.scalar(select(Content.id).where(Content.content_hash == staged.content_hash)) is None:
                    storage.cleanup_owned_file(final_path, True)
            except Exception:
                logger.exception("Retaining possible orphan upload file for safe recovery")
            finally:
                db.rollback()


@router.post("/{document_id}/retry", response_model=DocumentSummary)
def retry_document(course_id: int, document_id: int, background_tasks: BackgroundTasks,
                   response: Response, db: Session = Depends(get_db)) -> DocumentSummary:
    if lock_course(db, course_id) is None:
        raise HTTPException(404, "Course not found")
    document = _scoped_document(db, course_id, document_id)
    content = lock_content(db, document.content_id)
    if content.status == "pending_cleanup":
        raise HTTPException(409, "Content is pending cleanup")
    eligible = content.status in {"failed", "uploaded"}
    if eligible:
        content.status = "uploaded"
    result = summary(document, content)
    content_id = content.id
    db.commit()
    if eligible:
        response.status_code = 202
        jobs.schedule_content_processing(background_tasks, content_id)
    return result


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(course_id: int, document_id: int, background_tasks: BackgroundTasks,
                    db: Session = Depends(get_db)) -> Response:
    if lock_course(db, course_id) is None:
        raise HTTPException(404, "Course not found")
    document = _scoped_document(db, course_id, document_id)
    content = lock_content(db, document.content_id)
    content_id = content.id
    db.delete(document)
    db.flush()
    cleanup = mark_unreferenced(db, content)
    db.commit()
    if cleanup:
        jobs.schedule_content_cleanup(background_tasks, content_id)
    return Response(status_code=204)
