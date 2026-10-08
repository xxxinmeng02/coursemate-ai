from typing import TYPE_CHECKING, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.content import Content


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "content_id",
            "chunk_index",
            name="uq_chunks_content_id_chunk_index",
        ),
        CheckConstraint(
            "(embedding IS NULL) = (embedding_config IS NULL)",
            name="ck_chunks_embedding_pair",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(
        ForeignKey("contents.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Fixed to the schema dimension; changing it requires a new migration.
    # SQLite is used only for non-vector tests, never for similarity search.
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(1536).with_variant(JSON(none_as_null=True), "sqlite"), nullable=True,
    )
    embedding_config: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    content: Mapped["Content"] = relationship(back_populates="chunks")
