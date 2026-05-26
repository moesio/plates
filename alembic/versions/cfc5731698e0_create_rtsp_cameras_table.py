"""create rtsp_cameras table

Revision ID: cfc5731698e0
Revises: b93a99c371b7
Create Date: 2026-05-26 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cfc5731698e0'
down_revision: Union[str, Sequence[str], None] = 'b93a99c371b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rtsp_cameras',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default=sa.text('554')),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('password', sa.String(length=100), nullable=True),
        sa.Column('path', sa.String(length=255), nullable=True, server_default=sa.text("'/'")),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('rtsp_cameras')
