import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class UserProfileBase(BaseModel):
    user_id: str
    preferences_json: dict[str, Any] | None = None


class UserProfileCreate(UserProfileBase):
    pass


class UserProfileRead(UserProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
