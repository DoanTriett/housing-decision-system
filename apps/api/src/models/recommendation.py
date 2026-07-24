import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class Recommendation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "recommendations"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ranked_listings: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    trade_off_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
