"""add campos CT-e no documento

Revision ID: 003
Revises: 002
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Campos específicos de CT-e; nullable para compatibilidade com NF-e existentes
    op.add_column("documento", sa.Column("modal", sa.String(2)))   # 01=rodoviário, 02=aéreo…
    op.add_column("documento", sa.Column("tomador", sa.String(1))) # 0=rem,1=exped,2=receb,3=dest
    op.add_column("documento", sa.Column("rem_cnpj", sa.String(14)))  # remetente (CT-e)
    op.add_column("documento", sa.Column("rec_cnpj", sa.String(14)))  # recebedor (CT-e)

    # Índice de endpoint SEFAZ (armazena qual endpoint respondeu — útil para debug UF)
    op.add_column("distribuicao_estado", sa.Column("endpoint_usado", sa.Text))

    # Endpoint configurável no config.py — campo de config apenas, sem migração de dado


def downgrade() -> None:
    op.drop_column("distribuicao_estado", "endpoint_usado")
    op.drop_column("documento", "rec_cnpj")
    op.drop_column("documento", "rem_cnpj")
    op.drop_column("documento", "tomador")
    op.drop_column("documento", "modal")
