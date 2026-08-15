"""add unique constraint on course name

Revision ID: 9a2f1c0e4b7d
Revises: 060be81400d7
Create Date: 2026-08-15 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a2f1c0e4b7d'
down_revision: Union[str, Sequence[str], None] = '060be81400d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a unique constraint so duplicate course names cannot be stored."""
    op.create_unique_constraint('uq_courses_name', 'courses', ['name'])


def downgrade() -> None:
    """Remove the unique constraint on course names."""
    op.drop_constraint('uq_courses_name', 'courses', type_='unique')
