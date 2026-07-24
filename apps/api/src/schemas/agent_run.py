import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentRunBase(BaseModel):
    request_id: uuid.UUID
    agent_name: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tokens_used: int | None = None
    cost_usd: float | None = None
    output_json: dict[str, Any] | None = None


class AgentRunCreate(AgentRunBase):
    pass


class AgentRunRead(AgentRunBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
