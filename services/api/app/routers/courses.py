from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.course import Course
from app.models.document import Document
from app.schemas.course import (
    CourseCreate,
    CourseDetail,
    CourseSummary,
    DocumentSummary,
)

router = APIRouter(prefix="/courses", tags=["courses"])

MAX_NAME_ATTEMPTS = 5


def _next_available_name(db: Session, base_name: str) -> str:
    """Return the first unused name following the ``Base (1)`` convention.

    Existing names that equal ``base_name`` or start with ``base_name + " ("``
    are considered taken. The lowest free numeric suffix is chosen so deleted
    duplicates leave reusable gaps, similar to how macOS names copies.
    """
    prefix = f"{base_name} ("
    existing = set(
        db.execute(
            select(Course.name).where(
                (Course.name == base_name) | Course.name.startswith(prefix)
            )
        )
        .scalars()
        .all()
    )

    if base_name not in existing:
        return base_name

    index = 1
    while f"{base_name} ({index})" in existing:
        index += 1
    return f"{base_name} ({index})"


@router.post("", response_model=CourseSummary, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    """Create a course, generating a unique name on exact duplicates."""
    base_name = payload.name

    for _ in range(MAX_NAME_ATTEMPTS):
        name = _next_available_name(db, base_name)
        course = Course(name=name)
        db.add(course)

        try:
            db.commit()
        except IntegrityError:
            # Another request inserted the same name between our check and
            # commit. Roll back and retry with the next available name.
            db.rollback()
            continue

        db.refresh(course)
        return course

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not generate a unique course name",
    )


@router.get("", response_model=list[CourseSummary])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    """Return the list of courses without loading documents or chunks."""
    return list(db.execute(select(Course).order_by(Course.id)).scalars().all())


@router.get("/{course_id}", response_model=CourseDetail)
def get_course(course_id: int, db: Session = Depends(get_db)) -> CourseDetail:
    """Return a course together with its documents and their content status."""
    course = db.execute(
        select(Course)
        .options(selectinload(Course.documents).selectinload(Document.content))
        .where(Course.id == course_id)
    ).scalar_one_or_none()

    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    documents = sorted(course.documents, key=lambda doc: doc.id)
    return CourseDetail(
        id=course.id,
        name=course.name,
        created_at=course.created_at,
        documents=[
            DocumentSummary(
                id=doc.id,
                name=doc.name,
                created_at=doc.created_at,
                status=doc.content.status,
            )
            for doc in documents
        ],
    )


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a course. Its documents are removed via the existing cascade."""
    course = db.get(Course, course_id)

    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    db.delete(course)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
