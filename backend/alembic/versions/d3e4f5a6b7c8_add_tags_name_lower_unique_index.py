"""add_tags_name_lower_unique_index

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-26 00:00:00.000000

Adds a functional unique index on lower(name) on tags table to enforce case-insensitive uniqueness.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_tags_name_lower',
        'tags',
        [sa.text('lower(name)')],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_tags_name_lower', table_name='tags')
