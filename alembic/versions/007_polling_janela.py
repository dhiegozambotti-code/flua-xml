"""007: janela de polling (consulta noturna) na empresa.

Revision ID: 007
Revises: 006
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("empresa", sa.Column("polling_janela_inicio", sa.Integer(), nullable=True))
    op.add_column("empresa", sa.Column("polling_janela_fim", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("empresa", "polling_janela_fim")
    op.drop_column("empresa", "polling_janela_inicio")
