"""add_asset_tags

Revision ID: c2d3e4f5a6b7
Revises: b7e0c1a2d3f4
Create Date: 2026-09-26 00:00:00.000000

Adds Tag table and asset_tags association table relating Tag <-> MediaAsset (many-to-many).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b7e0c1a2d3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create tags table
    op.create_table(
        'tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tags_id', 'tags', ['id'], unique=False)
    op.create_index('ix_tags_name', 'tags', ['name'], unique=True)

    # 2. Create asset_tags association table
    op.create_table(
        'asset_tags',
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('media_assets.id', ondelete='CASCADE'), primary_key=True, nullable=False),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True, nullable=False),
        sa.PrimaryKeyConstraint('asset_id', 'tag_id')
    )
    op.create_index('ix_asset_tags_asset_id', 'asset_tags', ['asset_id'], unique=False)
    op.create_index('ix_asset_tags_tag_id', 'asset_tags', ['tag_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_asset_tags_tag_id', table_name='asset_tags')
    op.drop_index('ix_asset_tags_asset_id', table_name='asset_tags')
    op.drop_table('asset_tags')
    op.drop_index('ix_tags_name', table_name='tags')
    op.drop_index('ix_tags_id', table_name='tags')
    op.drop_table('tags')
