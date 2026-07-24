import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ListingBase(BaseModel):
    title: str
    address: str
    neighborhood: str
    city: str = "Austin"
    lat: float
    lon: float
    price_monthly: int
    beds: float
    baths: float
    sqft: int
    has_laundry: bool = False
    is_pet_friendly: bool = False
    description: str
    is_active: bool = True


class ListingCreate(ListingBase):
    pass


class ListingRead(ListingBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
