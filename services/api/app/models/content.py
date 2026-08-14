from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.document import Document


class Content(Base):
    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('uploaded', 'processing', 'ready', 'failed', 'pending_cleanup')",
            name="ck_contents_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="uploaded",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="content",
        passive_deletes="all",
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="content",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
