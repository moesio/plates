"""add detect_grid to rtsp_cameras

Revision ID: a1b2c3d4e5f6
Revises: 4740b848cbd8
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4740b848cbd8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('rtsp_cameras',
        sa.Column('detect_grid', sa.String(length=10), nullable=True,
                  server_default=sa.text("'1x1'")),
    )


def downgrade() -> None:
    op.drop_column('rtsp_cameras', 'detect_grid')