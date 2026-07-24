import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRequestBase(BaseModel):
    user_id: str
    raw_text: str
    budget_max: int | None = None
    anchor_address: str | None = None
    max_commute_minutes: int | None = None
    requires_laundry: bool = False
    requires_pet_friendly: bool = False
    status: str = "pending"


class UserRequestCreate(UserRequestBase):
    pass


class UserRequestRead(UserRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
