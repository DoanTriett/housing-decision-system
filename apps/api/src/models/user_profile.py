from typing import Any

from sqlalchemy import Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class UserProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profiles_user_id"),)

    user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    preferences_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
