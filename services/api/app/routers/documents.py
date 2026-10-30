from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import document_processing, storage
from app.database import get_db, get_session_factory
from app.models.content import Content
from app.models.course import Course
from app.models.document import Document
from app.schemas.course import DocumentSummary

router = APIRouter(
    prefix="/courses/{course_id}/documents",
    tags=["documents"],
)


@router.post("", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
async def upload_document(
    course_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentSummary:
    """Upload one PDF, attach its deduplicated content, and queue processing.

    New content is parsed and embedded after the response is sent. Reused
    content that is already searchable or failed is not processed again.
    """
    if db.get(Course, course_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    staged_upload: storage.StagedUpload | None = None
    final_path = None
    owns_final_file = False
    committed = False

    try:
        try:
            staged_upload = await storage.stage_pdf_upload(file)
        except storage.DocumentTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=str(exc),
            ) from exc
        except storage.InvalidPdfError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        content = db.scalar(
            select(Content).where(
                Content.content_hash == staged_upload.content_hash,
            )
        )

        if content is not None:
            duplicate_document = db.scalar(
                select(Document).where(
                    Document.course_id == course_id,
                    Document.content_id == content.id,
                )
            )
            if duplicate_document is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This document is already attached to the course",
                )

            document = Document(
                course_id=course_id,
                content_id=content.id,
                name=file.filename or "document.pdf",
            )
            db.add(document)
        else:
            final_path, owns_final_file = storage.promote_staged_upload(
                staged_upload
            )
            content = Content(
                content_hash=staged_upload.content_hash,
                storage_key=storage.storage_key_for_hash(staged_upload.content_hash),
                file_type="application/pdf",
                status="uploaded",
            )
            document = Document(
                course_id=course_id,
                content=content,
                name=file.filename or "document.pdf",
            )
            db.add(document)

        db.commit()
        committed = True
        db.refresh(document)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save document",
        ) from exc
    finally:
        storage.discard_staged_upload(staged_upload)
        storage.cleanup_owned_file(final_path, owns_final_file and not committed)

    # The document is saved; processing problems are reported via its state.
    state = document_processing.processing_states(db, [content])[content.id]
    if state == "not_indexed" and document_processing.claim(content.id):
        background_tasks.add_task(
            document_processing.run_pipeline, session_factory, content.id,
        )
        state = "processing"
    return _summary(document, content, state)


@router.post(
    "/{document_id}/process",
    response_model=DocumentSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_document_processing(
    course_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentSummary:
    """Queue parsing/embedding again for a failed or unsearchable document."""
    document = db.get(Document, document_id)
    if document is None or document.course_id != course_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    content = document.content
    state = document_processing.processing_states(db, [content])[content.id]
    if state not in document_processing.RETRYABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is {state.replace('_', ' ')}",
        )
    if content.status == "pending_cleanup":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document content is being removed",
        )

    if document_processing.claim(content.id):
        background_tasks.add_task(
            document_processing.run_pipeline, session_factory, content.id,
        )
    return _summary(document, content, "processing")


def _summary(
    document: Document,
    content: Content,
    state: document_processing.ProcessingState,
) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        name=document.name,
        created_at=document.created_at,
        status=content.status,
        processing_state=state,
    )
