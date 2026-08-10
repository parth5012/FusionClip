"""add_retry_fields

Revision ID: a1b2c3d4e5f6
Revises: 95c3d48285e2
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '95c3d48285e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tasks', sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('tasks', sa.Column('last_retry_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'last_retry_at')
    op.drop_column('tasks', 'max_retries')
    op.drop_column('tasks', 'retry_count')
