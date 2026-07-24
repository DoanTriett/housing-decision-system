from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class UserRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "user_requests"

    user_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    budget_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_commute_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_laundry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_pet_friendly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", index=True)
