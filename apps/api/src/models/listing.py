from sqlalchemy import Boolean, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class Listing(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "listings"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    neighborhood: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False, default="Austin")
    lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    lon: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    price_monthly: Mapped[int] = mapped_column(Integer, nullable=False)
    beds: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False)
    baths: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False)
    sqft: Mapped[int] = mapped_column(Integer, nullable=False)
    has_laundry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pet_friendly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
