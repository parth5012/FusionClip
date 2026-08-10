"""add retry and error diagnostics fields to tasks

Revision ID: a1b2c3d4e5f6
Revises: 95c3d48285e2
Create Date: 2026-08-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '95c3d48285e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('error_type', sa.String(), nullable=True))
    op.add_column('tasks', sa.Column('traceback', sa.Text(), nullable=True))
    op.add_column('tasks', sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('tasks', sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False))
    op.add_column('tasks', sa.Column('last_retry_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('tasks', 'last_retry_at')
    op.drop_column('tasks', 'max_retries')
    op.drop_column('tasks', 'retry_count')
    op.drop_column('tasks', 'traceback')
    op.drop_column('tasks', 'error_type')
