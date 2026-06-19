"""009: direção (entrada/saida) por documento.

A distribuição DFe é um stream NSU único por CNPJ que traz documentos
recebidos (entrada) e emitidos pela própria empresa (saída). A direção
passa a ser classificada por documento (emit/dest vs CNPJ da empresa).

Revision ID: 009
Revises: 008
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documento",
        sa.Column("direcao", sa.String(length=12), nullable=False, server_default="entrada"),
    )


def downgrade() -> None:
    op.drop_column("documento", "direcao")
