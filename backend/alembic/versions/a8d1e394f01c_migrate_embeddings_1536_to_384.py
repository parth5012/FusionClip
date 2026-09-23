"""migrate_embeddings_1536_to_384

Revision ID: a8d1e394f01c
Revises: 95c3d48285e2
Create Date: 2026-09-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    from sqlalchemy.types import TypeDecorator, JSON

    class Vector(TypeDecorator):
        impl = JSON
        cache_ok = True

        def __init__(self, dim=384):
            super().__init__()
            self.dim = dim


# revision identifiers, used by Alembic.
revision: str = "a8d1e394f01c"
down_revision: Union[str, Sequence[str], None] = "95c3d48285e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Alter media_assets.embedding column from Vector(1536) to Vector(384)."""
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else ""

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE media_assets ALTER COLUMN embedding TYPE vector(384) USING NULL;"
        )
    else:
        # For non-PostgreSQL (SQLite/generic), alter if supported or no-op
        try:
            with op.batch_alter_table("media_assets") as batch_op:
                batch_op.alter_column(
                    "embedding",
                    type_=Vector(384),
                    existing_type=Vector(1536),
                    existing_nullable=True,
                )
        except Exception:
            pass


def downgrade() -> None:
    """Revert media_assets.embedding column from Vector(384) to Vector(1536)."""
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else ""

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE media_assets ALTER COLUMN embedding TYPE vector(1536) USING NULL;"
        )
    else:
        try:
            with op.batch_alter_table("media_assets") as batch_op:
                batch_op.alter_column(
                    "embedding",
                    type_=Vector(1536),
                    existing_type=Vector(384),
                    existing_nullable=True,
                )
        except Exception:
            pass
