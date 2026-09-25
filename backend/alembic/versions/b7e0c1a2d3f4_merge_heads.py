"""merge heads a1b2c3d4e5f7, a8d1e394f01c, f998b595111b

Revision ID: b7e0c1a2d3f4
Revises: a1b2c3d4e5f7, a8d1e394f01c, f998b595111b
Create Date: 2026-09-25

"""
from typing import Sequence, Union

revision: str = 'b7e0c1a2d3f4'
down_revision: Union[str, Sequence[str], None] = (
    'a1b2c3d4e5f7',
    'a8d1e394f01c',
    'f998b595111b',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
