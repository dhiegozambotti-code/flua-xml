"""schema inicial

Revision ID: 001
Revises:
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "empresa",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organizacao_id", sa.String(36), nullable=False),
        sa.Column("cnpj", sa.String(14), nullable=False),
        sa.Column("razao_social", sa.Text),
        sa.Column("uf", sa.String(2)),
        sa.Column("regime", sa.String(20)),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organizacao_id", "cnpj", name="uq_empresa_org_cnpj"),
    )
    op.create_index("ix_empresa_organizacao_id", "empresa", ["organizacao_id"])

    op.create_table(
        "certificado",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresa.id"), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False, server_default="A1"),
        sa.Column("pfx_cifrado", sa.LargeBinary, nullable=False),
        sa.Column("senha_cifrada", sa.LargeBinary, nullable=False),
        sa.Column("fingerprint", sa.String(128)),
        sa.Column("valido_de", sa.DateTime(timezone=True)),
        sa.Column("valido_ate", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="ativo"),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "distribuicao_estado",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresa.id"), nullable=False),
        sa.Column("modelo", sa.String(10), nullable=False),
        sa.Column("ult_nsu", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("max_nsu", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ativo"),
        sa.Column("bloqueado_ate", sa.DateTime(timezone=True)),
        sa.Column("proximo_polling", sa.DateTime(timezone=True)),
        sa.Column("ultimo_sucesso", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("empresa_id", "modelo", name="uq_distribuicao_empresa_modelo"),
    )

    op.create_table(
        "documento",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresa.id"), nullable=False),
        sa.Column("modelo", sa.String(10), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("nsu", sa.BigInteger, nullable=False),
        sa.Column("schema_xsd", sa.String(50)),
        sa.Column("chave", sa.String(44)),
        sa.Column("emit_cnpj", sa.String(14)),
        sa.Column("dest_cnpj", sa.String(14)),
        sa.Column("valor_total", sa.Numeric(15, 2)),
        sa.Column("dh_emissao", sa.DateTime(timezone=True)),
        sa.Column("situacao", sa.String(20)),
        sa.Column("storage_key", sa.Text),
        sa.Column("sha256", sa.String(64)),
        sa.Column("capturado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "modelo", "nsu", name="uq_documento_empresa_modelo_nsu"),
    )
    op.create_index("idx_doc_chave", "documento", ["chave"])
    op.create_index("idx_doc_empresa_data", "documento", ["empresa_id", "dh_emissao"])

    op.create_table(
        "manifestacao",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresa.id"), nullable=False),
        sa.Column("chave", sa.String(44), nullable=False),
        sa.Column("tipo_evento", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("protocolo", sa.String(50)),
        sa.Column("enviado_em", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "captura_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresa.id")),
        sa.Column("modelo", sa.String(10)),
        sa.Column("tipo_consulta", sa.String(20)),
        sa.Column("cstat", sa.Integer),
        sa.Column("xmotivo", sa.Text),
        sa.Column("qtd_docs", sa.Integer),
        sa.Column("latencia_ms", sa.Integer),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("captura_log")
    op.drop_table("manifestacao")
    op.drop_index("idx_doc_empresa_data", table_name="documento")
    op.drop_index("idx_doc_chave", table_name="documento")
    op.drop_table("documento")
    op.drop_table("distribuicao_estado")
    op.drop_table("certificado")
    op.drop_index("ix_empresa_organizacao_id", table_name="empresa")
    op.drop_table("empresa")
