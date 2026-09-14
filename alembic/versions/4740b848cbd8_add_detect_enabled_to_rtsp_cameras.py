"""add detect_enabled to rtsp_cameras

Revision ID: 4740b848cbd8
Revises: cfc5731698e0
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4740b848cbd8'
down_revision: Union[str, Sequence[str], None] = 'cfc5731698e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('rtsp_cameras',
        sa.Column('detect_enabled', sa.Boolean(), nullable=True, server_default=sa.text('true')),
    )


def downgrade() -> None:
    op.drop_column('rtsp_cameras', 'detect_enabled')