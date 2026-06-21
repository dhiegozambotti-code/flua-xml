"""011: trava de envio ao ERP por modelo×direção no WebhookConfig.

Permite ligar/desligar o webhook documento.capturado por (modelo, direção),
para rollout controlado conforme o handler de cada tipo fica pronto no ERP.
Default seguro: coluna nula => não envia nada (liga-se tipo por tipo).

Revision ID: 011
Revises: 010
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_config", sa.Column("filtro_envio", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_config", "filtro_envio")
