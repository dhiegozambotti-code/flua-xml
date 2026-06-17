"""add tipo_fluxo a distribuicao_estado

Revision ID: 002
Revises: 001
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "distribuicao_estado",
        sa.Column("tipo_fluxo", sa.String(10), nullable=False, server_default="entrada"),
    )
    # Remove constraint antiga (empresa_id, modelo) e cria (empresa_id, modelo, tipo_fluxo)
    op.drop_constraint("uq_distribuicao_empresa_modelo", "distribuicao_estado")
    op.create_unique_constraint(
        "uq_distribuicao_empresa_modelo_fluxo",
        "distribuicao_estado",
        ["empresa_id", "modelo", "tipo_fluxo"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_distribuicao_empresa_modelo_fluxo", "distribuicao_estado")
    op.create_unique_constraint(
        "uq_distribuicao_empresa_modelo",
        "distribuicao_estado",
        ["empresa_id", "modelo"],
    )
    op.drop_column("distribuicao_estado", "tipo_fluxo")
