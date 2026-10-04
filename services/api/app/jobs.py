"""Best-effort in-process jobs. Arguments contain IDs, never request sessions."""
import logging

from fastapi import BackgroundTasks

from app import storage
from app.content_lifecycle import has_documents, lock_content, lock_content_hash
from app.database import get_session_factory
from app.models.content import Content
from app.parsing import process_content

logger = logging.getLogger(__name__)


def process_content_job(content_id: int) -> None:
    try:
        with get_session_factory()() as db:
            content = lock_content(db, content_id)
            if content is None or content.status != "uploaded" or not has_documents(db, content_id):
                return
            # Keep the state check and processing under the same transaction lock.
            process_content(db, content)
    except Exception:
        logger.exception("Background processing failed for content_id=%s", content_id)


def cleanup_content_job(content_id: int) -> None:
    try:
        with get_session_factory()() as db:
            content = db.get(Content, content_id)
            if content is None:
                return
            lock_content_hash(db, content.content_hash)
            content = lock_content(db, content_id)
            if content is None or content.status != "pending_cleanup" or has_documents(db, content_id):
                return
            # Detachment/pending intent was committed by the caller before this job.
            # A later COMMIT failure may leave a tombstone with an absent file;
            # missing_ok makes that state retryable without restoring live refs.
            storage.cleanup_owned_file(storage.storage_path_for_hash(content.content_hash), True)
            db.delete(content)
            db.commit()
    except Exception:
        logger.exception("Cleanup retained pending tombstone for content_id=%s", content_id)


def schedule_content_processing(tasks: BackgroundTasks, content_id: int) -> None:
    _schedule(tasks, process_content_job, content_id)


def schedule_content_cleanup(tasks: BackgroundTasks, content_id: int) -> None:
    _schedule(tasks, cleanup_content_job, content_id)


def _schedule(tasks, job, content_id):
    try:
        tasks.add_task(job, content_id)
    except Exception:
        logger.exception("Could not schedule %s for content_id=%s", job.__name__, content_id)
