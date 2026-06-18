import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Empresa(Base):
    __tablename__ = "empresa"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organizacao_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    razao_social: Mapped[Optional[str]] = mapped_column(Text)
    uf: Mapped[Optional[str]] = mapped_column(String(2))
    regime: Mapped[Optional[str]] = mapped_column(String(20))  # simples | presumido | normal
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Janela de polling (consulta noturna): horas 0–23. Ambos nulos = 24h.
    # Suporta janela que cruza a meia-noite (ex: inicio=20, fim=6).
    polling_janela_inicio: Mapped[Optional[int]] = mapped_column(Integer)
    polling_janela_fim: Mapped[Optional[int]] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    certificados: Mapped[List["Certificado"]] = relationship(back_populates="empresa")
    distribuicao_estados: Mapped[List["DistribuicaoEstado"]] = relationship(back_populates="empresa")
    documentos: Mapped[List["Documento"]] = relationship(back_populates="empresa")
    manifestacoes: Mapped[List["Manifestacao"]] = relationship(back_populates="empresa")
    capturas_log: Mapped[List["CapturaLog"]] = relationship(back_populates="empresa")

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("organizacao_id", "cnpj", name="uq_empresa_org_cnpj"),
    )


class Certificado(Base):
    __tablename__ = "certificado"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(String(36), ForeignKey("empresa.id"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="A1")
    pfx_cifrado: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    senha_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(128))
    valido_de: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valido_ate: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="certificados")


class DistribuicaoEstado(Base):
    __tablename__ = "distribuicao_estado"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(String(36), ForeignKey("empresa.id"), nullable=False)
    modelo: Mapped[str] = mapped_column(String(10), nullable=False)       # nfe | nfce | cte | mdfe
    tipo_fluxo: Mapped[str] = mapped_column(String(10), nullable=False, default="entrada")  # entrada | saida
    ult_nsu: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_nsu: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ativo")
    bloqueado_ate: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    proximo_polling: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ultimo_sucesso: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    endpoint_usado: Mapped[Optional[str]] = mapped_column(Text)

    empresa: Mapped["Empresa"] = relationship(back_populates="distribuicao_estados")

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "empresa_id", "modelo", "tipo_fluxo",
            name="uq_distribuicao_empresa_modelo_fluxo",
        ),
    )


class Documento(Base):
    __tablename__ = "documento"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(String(36), ForeignKey("empresa.id"), nullable=False)
    modelo: Mapped[str] = mapped_column(String(10), nullable=False)  # nfe | nfce | cte | mdfe
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)    # resumo | completo | evento
    nsu: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_xsd: Mapped[Optional[str]] = mapped_column(String(50))
    chave: Mapped[Optional[str]] = mapped_column(String(44), index=True)
    emit_cnpj: Mapped[Optional[str]] = mapped_column(String(14))
    dest_cnpj: Mapped[Optional[str]] = mapped_column(String(14))
    valor_total: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    dh_emissao: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    situacao: Mapped[Optional[str]] = mapped_column(String(20))  # autorizada | cancelada | denegada
    storage_key: Mapped[Optional[str]] = mapped_column(Text)
    # XML completo comprimido (gzip) — armazenamento persistente no Postgres,
    # imune a redeploys (o disco local da Railway é efêmero).
    xml_gz: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    capturado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Campos específicos CT-e
    modal: Mapped[Optional[str]] = mapped_column(String(2))    # 01=rodoviário, 02=aéreo …
    tomador: Mapped[Optional[str]] = mapped_column(String(1))  # 0=rem,1=exped,2=receb,3=dest
    rem_cnpj: Mapped[Optional[str]] = mapped_column(String(14))  # remetente
    rec_cnpj: Mapped[Optional[str]] = mapped_column(String(14))  # recebedor
    # Campos emitente (extraídos do XML completo)
    emit_razao_social: Mapped[Optional[str]] = mapped_column(Text)
    emit_ie: Mapped[Optional[str]] = mapped_column(String(20))
    emit_xlogradouro: Mapped[Optional[str]] = mapped_column(Text)
    emit_xmun: Mapped[Optional[str]] = mapped_column(String(100))
    emit_uf: Mapped[Optional[str]] = mapped_column(String(2))
    emit_cep: Mapped[Optional[str]] = mapped_column(String(8))
    # Número/série da NF-e
    numero: Mapped[Optional[str]] = mapped_column(String(20))
    serie: Mapped[Optional[str]] = mapped_column(String(5))
    # Totais fiscais (NF-e)
    v_prod: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_frete: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_seg: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_desc: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_ipi: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_icms: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_pis: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    v_cofins: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    # JSON serializado de itens e duplicatas (para webhook)
    itens_json: Mapped[Optional[str]] = mapped_column(Text)
    duplicatas_json: Mapped[Optional[str]] = mapped_column(Text)
    # Campos IBSCBS — Reforma Tributária NT 2026.001
    ibscbs_cst: Mapped[Optional[str]] = mapped_column(String(4))
    ibscbs_cclass_trib: Mapped[Optional[str]] = mapped_column(String(10))
    ibscbs_nbs: Mapped[Optional[str]] = mapped_column(String(20))
    # Campos específicos MDF-e
    mdfe_uf_ini: Mapped[Optional[str]] = mapped_column(String(2))
    mdfe_uf_fim: Mapped[Optional[str]] = mapped_column(String(2))
    mdfe_qtd_cte: Mapped[Optional[int]] = mapped_column(Integer)
    mdfe_qtd_nfe: Mapped[Optional[int]] = mapped_column(Integer)

    empresa: Mapped["Empresa"] = relationship(back_populates="documentos")

    @property
    def tem_xml(self) -> bool:
        """True se o XML está disponível (no banco ou em disco)."""
        return bool(self.xml_gz or self.storage_key)

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("empresa_id", "modelo", "nsu", name="uq_documento_empresa_modelo_nsu"),
    )


class Manifestacao(Base):
    __tablename__ = "manifestacao"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(String(36), ForeignKey("empresa.id"), nullable=False)
    chave: Mapped[str] = mapped_column(String(44), nullable=False)
    tipo_evento: Mapped[str] = mapped_column(String(10), nullable=False)  # 210200 | 210210 | 210220 | 210240
    status: Mapped[str] = mapped_column(String(20), nullable=False)       # pendente | enviado | rejeitado
    protocolo: Mapped[Optional[str]] = mapped_column(String(50))
    enviado_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    empresa: Mapped["Empresa"] = relationship(back_populates="manifestacoes")


class ApiKey(Base):
    """Chave de API por organização para autenticação do ERP Flua."""
    __tablename__ = "api_key"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organizacao_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(128), nullable=False)
    chave_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # sha256 hex
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookConfig(Base):
    """Configuração de webhook por organização."""
    __tablename__ = "webhook_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organizacao_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    secret: Mapped[Optional[str]] = mapped_column(String(64))  # HMAC-SHA256
    # CSV de eventos: documento.capturado, empresa.bloqueada_656, certificado.expirando
    eventos: Mapped[str] = mapped_column(
        String(512), nullable=False,
        default="documento.capturado,empresa.bloqueada_656",
    )
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapturaLog(Base):
    __tablename__ = "captura_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    empresa_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("empresa.id"))
    modelo: Mapped[Optional[str]] = mapped_column(String(10))
    tipo_consulta: Mapped[Optional[str]] = mapped_column(String(20))  # distNSU | consNSU | consChNFe
    cstat: Mapped[Optional[int]] = mapped_column(Integer)
    xmotivo: Mapped[Optional[str]] = mapped_column(Text)
    qtd_docs: Mapped[Optional[int]] = mapped_column(Integer)
    latencia_ms: Mapped[Optional[int]] = mapped_column(Integer)
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped[Optional["Empresa"]] = relationship(back_populates="capturas_log")
