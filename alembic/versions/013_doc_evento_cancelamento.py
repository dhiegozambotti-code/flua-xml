"""013: tipo_evento + cancelado_em no Documento (eventos de cancelamento).

Permite identificar o código do evento e marcar a nota original como
cancelada quando um evento de cancelamento (NFS-e 101101 / NF-e 110111) é
vinculado pela chave.

Revision ID: 013
Revises: 012
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documento", sa.Column("tipo_evento", sa.String(length=10), nullable=True))
    op.add_column("documento", sa.Column("cancelado_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("documento", "cancelado_em")
    op.drop_column("documento", "tipo_evento")
