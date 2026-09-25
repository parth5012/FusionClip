"""add_source_path_to_media_assets

Revision ID: f998b595111b
Revises: 95c3d48285e2
Create Date: 2026-08-16 00:00:00.000000

Adds ``MediaAsset.source_path`` — the optional link from a derived asset
(e.g. an upscaled output) back to the original it was generated from.
Used by the before/after comparison UI (wayfinder map #56 / #58).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f998b595111b'
down_revision: Union[str, Sequence[str], None] = '95c3d48285e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the source_path column (nullable, indexed) to media_assets."""
    op.add_column(
        'media_assets',
        sa.Column('source_path', sa.String(), nullable=True),
    )
    op.create_index(
        'ix_media_assets_source_path', 'media_assets', ['source_path'], unique=False
    )


def downgrade() -> None:
    """Drop the source_path column and its index."""
    op.drop_index('ix_media_assets_source_path', table_name='media_assets')
    op.drop_column('media_assets', 'source_path')
