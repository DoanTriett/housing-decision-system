"""Add result_context JSON to recommendations for Day 12 map/trade-off data."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c4d6e8f0a1"
down_revision: Union[str, None] = "9c659660954c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("result_context", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "result_context")
