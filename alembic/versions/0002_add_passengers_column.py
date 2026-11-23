"""add_passengers_column

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23 18:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Lotação a bordo por leitura; nula nos pacotes anteriores à coluna."""
    op.add_column('telemetria', sa.Column('passengers', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('telemetria', 'passengers')
