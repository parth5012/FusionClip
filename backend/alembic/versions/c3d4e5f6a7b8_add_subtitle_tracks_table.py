"""add subtitle_tracks table

Revision ID: c3d4e5f6a7b8
Revises: b7e0c1a2d3f4
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b7e0c1a2d3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'subtitle_tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('format', sa.String(), nullable=False, server_default='vtt'),
        sa.Column('track_type', sa.String(), nullable=False, server_default='sidecar'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subtitle_tracks_id'), 'subtitle_tracks', ['id'], unique=False)
    op.create_index(op.f('ix_subtitle_tracks_asset_id'), 'subtitle_tracks', ['asset_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_subtitle_tracks_asset_id'), table_name='subtitle_tracks')
    op.drop_index(op.f('ix_subtitle_tracks_id'), table_name='subtitle_tracks')
    op.drop_table('subtitle_tracks')
