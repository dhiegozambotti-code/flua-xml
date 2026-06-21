"""012: razão social do destinatário/tomador + status de integração ERP.

Colunas para amarrar a regra de importação no ERP (tomador, CFOP vem dos
itens) e acompanhar o ciclo de envio: enviado_erp_em (despachado, ERP 2xx) e
importado_erp_em (confirmado pelo ERP via callback).

Revision ID: 012
Revises: 011
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documento", sa.Column("dest_razao_social", sa.Text(), nullable=True))
    op.add_column("documento", sa.Column("enviado_erp_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documento", sa.Column("importado_erp_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("documento", "importado_erp_em")
    op.drop_column("documento", "enviado_erp_em")
    op.drop_column("documento", "dest_razao_social")
