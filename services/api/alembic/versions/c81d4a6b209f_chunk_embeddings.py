"""Add pgvector embeddings to canonical chunks.

Revision ID: c81d4a6b209f
Revises: 9a2f1c0e4b7d
"""
from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa

revision = "c81d4a6b209f"
down_revision = "9a2f1c0e4b7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.add_column("chunks", sa.Column("embedding", Vector(1536), nullable=True))
    op.add_column("chunks", sa.Column("embedding_config", sa.String(255), nullable=True))
    op.create_check_constraint(
        "ck_chunks_embedding_pair", "chunks",
        "(embedding IS NULL) = (embedding_config IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chunks_embedding_pair", "chunks", type_="check")
    op.drop_column("chunks", "embedding_config")
    op.drop_column("chunks", "embedding")
    # Other tables/apps may use the shared extension; do not uninstall it.
