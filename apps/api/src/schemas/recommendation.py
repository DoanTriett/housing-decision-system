import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RecommendationBase(BaseModel):
    request_id: uuid.UUID
    ranked_listings: list[dict[str, Any]] | None = None
    trade_off_narrative: str | None = None


class RecommendationCreate(RecommendationBase):
    pass


class RecommendationRead(RecommendationBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
