"""006: campo secret no webhook_config + campos fiscais no documento.

Revision ID: 006
Revises: 005
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Secret HMAC no webhook_config (para assinar eventos enviados ao ERP)
    op.add_column("webhook_config", sa.Column("secret", sa.String(64), nullable=True))

    # Campos fiscais no documento (para enriquecer webhook sem precisar re-parsear XML)
    op.add_column("documento", sa.Column("emit_razao_social", sa.Text(), nullable=True))
    op.add_column("documento", sa.Column("emit_ie", sa.String(20), nullable=True))
    op.add_column("documento", sa.Column("numero", sa.String(20), nullable=True))
    op.add_column("documento", sa.Column("serie", sa.String(5), nullable=True))
    op.add_column("documento", sa.Column("v_prod", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_frete", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_seg", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_desc", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_ipi", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_icms", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_pis", sa.Numeric(15, 2), nullable=True))
    op.add_column("documento", sa.Column("v_cofins", sa.Numeric(15, 2), nullable=True))
    # JSON array de itens e duplicatas (armazenados para envio no webhook)
    op.add_column("documento", sa.Column("itens_json", sa.Text(), nullable=True))
    op.add_column("documento", sa.Column("duplicatas_json", sa.Text(), nullable=True))
    op.add_column("documento", sa.Column("emit_xlogradouro", sa.Text(), nullable=True))
    op.add_column("documento", sa.Column("emit_xmun", sa.String(100), nullable=True))
    op.add_column("documento", sa.Column("emit_uf", sa.String(2), nullable=True))
    op.add_column("documento", sa.Column("emit_cep", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_config", "secret")
    for col in [
        "emit_razao_social", "emit_ie", "numero", "serie",
        "v_prod", "v_frete", "v_seg", "v_desc", "v_ipi", "v_icms", "v_pis", "v_cofins",
        "itens_json", "duplicatas_json",
        "emit_xlogradouro", "emit_xmun", "emit_uf", "emit_cep",
    ]:
        op.drop_column("documento", col)
