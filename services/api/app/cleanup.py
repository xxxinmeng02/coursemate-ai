"""Operator recovery: python -m app.cleanup (retry committed pending tombstones)."""
from sqlalchemy import select

from app.database import get_session_factory
from app.jobs import cleanup_content_job
from app.models.content import Content


def main() -> None:
    with get_session_factory()() as db:
        ids = list(db.scalars(select(Content.id).where(Content.status == "pending_cleanup")))
    for content_id in ids:
        cleanup_content_job(content_id)


if __name__ == "__main__":
    main()
