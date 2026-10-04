"""Enforce one attachment of a Content per Course.

Revision ID: c3a11d0c2026
Revises: 9a2f1c0e4b7d
"""
from alembic import op
import sqlalchemy as sa

revision = "c3a11d0c2026"
down_revision = "9a2f1c0e4b7d"
branch_labels = None
depends_on = None


def upgrade():
    duplicate = op.get_bind().execute(sa.text(
        "SELECT course_id, content_id FROM documents GROUP BY course_id, content_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate is not None:
        raise RuntimeError("Duplicate course/content attachments exist. Back up and explicitly reconcile duplicate Document rows before rerunning upgrade.")
    op.create_unique_constraint("uq_documents_course_content", "documents", ["course_id", "content_id"])


def downgrade():
    op.drop_constraint("uq_documents_course_content", "documents", type_="unique")
