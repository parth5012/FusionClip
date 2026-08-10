"""add_traceback_field

Revision ID: a1b2c3d4e5f7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-10 00:00:01.000000

"""
typing import Sequence, Union

alembic import  import sqlalchemy

revision: str 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] None
depends_on: Union[str, Sequence[str], None] None


defupgrade()None:
op.add_column('tasks',sa.Column('traceback',sa.Text()nullable=True))


defdowngrade()None:
op.drop_column('tasks', 'traceback')
