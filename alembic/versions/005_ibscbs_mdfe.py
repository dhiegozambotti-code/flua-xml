"""Fase 6: campos IBSCBS na tabela documento + suporte MDF-e no distribuicao_estado.

Revision ID: 005
Revises: 004
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Campos IBSCBS (Reforma Tributária NT 2026.001)
    op.add_column("documento", sa.Column("ibscbs_cst", sa.String(4), nullable=True))
    op.add_column("documento", sa.Column("ibscbs_cclass_trib", sa.String(10), nullable=True))
    op.add_column("documento", sa.Column("ibscbs_nbs", sa.String(20), nullable=True))

    # Campos específicos MDF-e
    op.add_column("documento", sa.Column("mdfe_uf_ini", sa.String(2), nullable=True))
    op.add_column("documento", sa.Column("mdfe_uf_fim", sa.String(2), nullable=True))
    op.add_column("documento", sa.Column("mdfe_qtd_cte", sa.Integer(), nullable=True))
    op.add_column("documento", sa.Column("mdfe_qtd_nfe", sa.Integer(), nullable=True))


def downgrade() -> None:
    for col in ("mdfe_qtd_nfe", "mdfe_qtd_cte", "mdfe_uf_fim", "mdfe_uf_ini",
                "ibscbs_nbs", "ibscbs_cclass_trib", "ibscbs_cst"):
        op.drop_column("documento", col)
