"""Fase 4: tabelas api_key e webhook_config.

Revision ID: 004
Revises: 003
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organizacao_id", sa.String(128), nullable=False),
        sa.Column("nome", sa.String(128), nullable=False),
        sa.Column("chave_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_api_key_org", "api_key", ["organizacao_id"])

    op.create_table(
        "webhook_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organizacao_id", sa.String(128), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column(
            "eventos", sa.String(512), nullable=False,
            server_default="documento.capturado,empresa.bloqueada_656",
        ),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_webhook_org", "webhook_config", ["organizacao_id"])


def downgrade() -> None:
    op.drop_table("webhook_config")
    op.drop_table("api_key")
