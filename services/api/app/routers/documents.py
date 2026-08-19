from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.database import get_db
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
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentSummary:
    """Upload one PDF and attach its deduplicated content to a course."""
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

        return DocumentSummary(
            id=document.id,
            name=document.name,
            created_at=document.created_at,
            status=content.status,
        )
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
