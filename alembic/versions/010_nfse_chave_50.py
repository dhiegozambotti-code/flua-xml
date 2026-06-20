"""010: chave do Documento para String(50) — suportar NFS-e Nacional.

A chave de acesso da NFS-e do Padrão Nacional tem 50 dígitos (NF-e/CT-e/MDF-e
têm 44). Ampliar a coluna para comportar ambas.

Revision ID: 010
Revises: 009
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "documento", "chave",
        existing_type=sa.String(length=44),
        type_=sa.String(length=50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "documento", "chave",
        existing_type=sa.String(length=50),
        type_=sa.String(length=44),
        existing_nullable=True,
    )
