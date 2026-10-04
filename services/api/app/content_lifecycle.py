"""Transaction-held locks shared by upload, processing and deletion."""
from sqlalchemy import select, update, text
from sqlalchemy.orm import Session

from app.models.content import Content
from app.models.course import Course
from app.models.document import Document


def lock_content(db: Session, content_id: int) -> Content | None:
    return db.scalars(
        update(Content).where(Content.id == content_id).values(status=Content.status)
        .returning(Content)
        .execution_options(populate_existing=True, synchronize_session=False)
    ).one_or_none()


def lock_course(db: Session, course_id: int) -> Course | None:
    return db.scalars(
        update(Course).where(Course.id == course_id).values(name=Course.name)
        .returning(Course)
        .execution_options(populate_existing=True, synchronize_session=False)
    ).one_or_none()


def lock_content_hash(db: Session, content_hash: str) -> None:
    # Hash locks serialize creation and file disposal even when no row exists.
    if db.get_bind().dialect.name == "postgresql":
        key = int(content_hash[:16], 16)
        if key >= 2**63:
            key -= 2**64
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    else:
        db.execute(update(Content).where(Content.content_hash == content_hash)
                   .values(status=Content.status))


def has_documents(db: Session, content_id: int) -> bool:
    return db.scalar(select(Document.id).where(Document.content_id == content_id).limit(1)) is not None


def mark_unreferenced(db: Session, content: Content) -> bool:
    if has_documents(db, content.id):
        return False
    content.status = "pending_cleanup"
    return True
