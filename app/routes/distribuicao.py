"""Rotas para gerenciar estados de distribuição NSU, manifestações e documentos."""

import io
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func as sqlfunc

from app.db import get_db
from app.models import CapturaLog, DistribuicaoEstado, Documento, Empresa, Manifestacao
from app.services.alertas import alertas_empresa
from app.services.manifestacao import enfileirar as enfileirar_manifestacao
from app.services.orquestrador import poll_empresa_modelo
from app.services.storage import load_xml, load_xml_doc

router = APIRouter(tags=["distribuicao"])


# ---- schemas ----------------------------------------------------------------

class DistribuicaoCreate(BaseModel):
    modelo: str  # nfe | nfce | cte | mdfe


class DistribuicaoOut(BaseModel):
    id: str
    empresa_id: str
    modelo: str
    tipo_fluxo: str
    ult_nsu: int
    max_nsu: int
    status: str
    bloqueado_ate: Optional[datetime]
    proximo_polling: Optional[datetime]
    ultimo_sucesso: Optional[datetime]

    model_config = {"from_attributes": True}


class DocumentoOut(BaseModel):
    id: str
    empresa_id: str
    modelo: str
    tipo: str
    nsu: int
    schema_xsd: Optional[str]
    chave: Optional[str]
    numero: Optional[str] = None
    serie: Optional[str] = None
    emit_cnpj: Optional[str]
    emit_razao_social: Optional[str] = None
    dest_cnpj: Optional[str]
    valor_total: Optional[float]
    dh_emissao: Optional[datetime]
    situacao: Optional[str]
    storage_key: Optional[str]
    tem_xml: bool = False
    sha256: Optional[str]
    capturado_em: datetime
    # CT-e
    modal: Optional[str] = None
    tomador: Optional[str] = None
    rem_cnpj: Optional[str] = None
    rec_cnpj: Optional[str] = None
    # IBSCBS
    ibscbs_cst: Optional[str] = None
    ibscbs_cclass_trib: Optional[str] = None
    ibscbs_nbs: Optional[str] = None
    # MDF-e
    mdfe_uf_ini: Optional[str] = None
    mdfe_uf_fim: Optional[str] = None
    mdfe_qtd_cte: Optional[int] = None
    mdfe_qtd_nfe: Optional[int] = None

    model_config = {"from_attributes": True}


class ManifestacaoCreate(BaseModel):
    chave: str
    tipo_evento: str = "210210"  # 210200 | 210210 | 210220 | 210240
    xjust: str = ""              # obrigatório para 210220 e 210240


class ManifestacaoOut(BaseModel):
    id: str
    empresa_id: str
    chave: str
    tipo_evento: str
    status: str
    protocolo: Optional[str]
    enviado_em: Optional[datetime]

    model_config = {"from_attributes": True}


# ---- endpoints de distribuição entrada --------------------------------------

@router.post("/empresas/{empresa_id}/distribuicao", response_model=DistribuicaoOut, status_code=201)
def iniciar_distribuicao(empresa_id: str, body: DistribuicaoCreate, db: Session = Depends(get_db)):
    """Ativa polling de entrada (documentos recebidos) para um modelo."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")

    existente = (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=body.modelo, tipo_fluxo="entrada")
        .first()
    )
    if existente:
        return existente

    estado = DistribuicaoEstado(empresa_id=empresa_id, modelo=body.modelo, tipo_fluxo="entrada")
    db.add(estado)
    db.commit()
    db.refresh(estado)
    return estado


# ---- endpoints de distribuição saída ----------------------------------------

@router.post("/empresas/{empresa_id}/distribuicao-saida", response_model=DistribuicaoOut, status_code=201)
def iniciar_distribuicao_saida(empresa_id: str, body: DistribuicaoCreate, db: Session = Depends(get_db)):
    """Ativa polling de saída (documentos emitidos pela própria empresa / NFC-e)."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")

    existente = (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=body.modelo, tipo_fluxo="saida")
        .first()
    )
    if existente:
        return existente

    estado = DistribuicaoEstado(empresa_id=empresa_id, modelo=body.modelo, tipo_fluxo="saida")
    db.add(estado)
    db.commit()
    db.refresh(estado)
    return estado


@router.get("/empresas/{empresa_id}/distribuicao", response_model=List[DistribuicaoOut])
def listar_distribuicao(empresa_id: str, db: Session = Depends(get_db)):
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")
    return db.query(DistribuicaoEstado).filter_by(empresa_id=empresa_id).all()


@router.post("/empresas/{empresa_id}/distribuicao/{modelo}/poll")
def disparar_poll(
    empresa_id: str,
    modelo: str,
    tipo_fluxo: str = "entrada",
    db: Session = Depends(get_db),
):
    """Dispara manualmente um ciclo de polling (útil para testes/debug)."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")
    estado = (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=modelo, tipo_fluxo=tipo_fluxo)
        .first()
    )
    if not estado:
        raise HTTPException(404, "Estado de distribuição não encontrado")

    estado.proximo_polling = None
    db.commit()

    try:
        poll_empresa_modelo(db, empresa_id, modelo, tipo_fluxo)
    except Exception as exc:
        raise HTTPException(500, f"Erro no polling: {exc}")

    db.refresh(estado)
    return {
        "status": "ok",
        "distribuicao_status": estado.status,
        "ult_nsu": estado.ult_nsu,
        "tipo_fluxo": estado.tipo_fluxo,
    }


@router.post("/empresas/{empresa_id}/distribuicao/{modelo}/set-nsu")
def ajustar_nsu(
    empresa_id: str,
    modelo: str,
    ult_nsu: int,
    tipo_fluxo: str = "entrada",
    db: Session = Depends(get_db),
):
    """Ajusta manualmente o ponteiro ult_nsu (ex: alinhar com distribuição já consumida no SEFAZ)."""
    estado = (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=modelo, tipo_fluxo=tipo_fluxo)
        .first()
    )
    if not estado:
        raise HTTPException(404, "Estado de distribuição não encontrado")
    anterior = estado.ult_nsu
    estado.ult_nsu = ult_nsu
    db.commit()
    db.refresh(estado)
    return {"status": "ok", "ult_nsu_anterior": anterior, "ult_nsu": estado.ult_nsu, "distribuicao_status": estado.status}


@router.post("/empresas/{empresa_id}/distribuicao/{modelo}/pausar")
def pausar_distribuicao(
    empresa_id: str,
    modelo: str,
    tipo_fluxo: str = "entrada",
    db: Session = Depends(get_db),
):
    """Pausa o polling de um modelo (status=pausado → excluído da varredura)."""
    estado = (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=modelo, tipo_fluxo=tipo_fluxo)
        .first()
    )
    if not estado:
        raise HTTPException(404, "Estado de distribuição não encontrado")
    estado.status = "pausado"
    db.commit()
    return {"status": "ok", "distribuicao_status": estado.status}


@router.post("/empresas/{empresa_id}/distribuicao/{modelo}/reativar")
def reativar_distribuicao(
    empresa_id: str,
    modelo: str,
    tipo_fluxo: str = "entrada",
    db: Session = Depends(get_db),
):
    """Reativa o polling de um modelo pausado."""
    estado = (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=modelo, tipo_fluxo=tipo_fluxo)
        .first()
    )
    if not estado:
        raise HTTPException(404, "Estado de distribuição não encontrado")
    estado.status = "ativo"
    db.commit()
    return {"status": "ok", "distribuicao_status": estado.status}


# ---- endpoints de manifestação ----------------------------------------------

@router.post("/empresas/{empresa_id}/manifestar", response_model=ManifestacaoOut, status_code=201)
def registrar_manifestacao(
    empresa_id: str,
    body: ManifestacaoCreate,
    db: Session = Depends(get_db),
):
    """Enfileira uma manifestação do destinatário (manual ou automática)."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")

    if body.tipo_evento not in ("210200", "210210", "210220", "210240"):
        raise HTTPException(422, "tipo_evento inválido")

    if body.tipo_evento in ("210220", "210240") and not body.xjust:
        raise HTTPException(422, "xjust obrigatório para este tipo_evento")

    mde = enfileirar_manifestacao(db, empresa_id, body.chave, body.tipo_evento, body.xjust)
    return mde


@router.get("/empresas/{empresa_id}/manifestacoes", response_model=List[ManifestacaoOut])
def listar_manifestacoes(
    empresa_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")
    q = db.query(Manifestacao).filter_by(empresa_id=empresa_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(Manifestacao.enviado_em.desc()).offset(offset).limit(limit).all()


# ---- endpoints de documentos ------------------------------------------------

def _filtra_documentos(db, empresa_id, modelo, tipo, de, ate, emit_cnpj, dest_cnpj):
    q = db.query(Documento).filter_by(empresa_id=empresa_id)
    if modelo:
        q = q.filter_by(modelo=modelo)
    if tipo:
        q = q.filter_by(tipo=tipo)
    if de:
        q = q.filter(Documento.dh_emissao >= de)
    if ate:
        q = q.filter(Documento.dh_emissao <= ate)
    if emit_cnpj:
        q = q.filter(Documento.emit_cnpj == emit_cnpj.strip())
    if dest_cnpj:
        q = q.filter(Documento.dest_cnpj == dest_cnpj.strip())
    return q


@router.get("/empresas/{empresa_id}/documentos", response_model=List[DocumentoOut])
def listar_documentos(
    empresa_id: str,
    modelo: Optional[str] = None,
    tipo: Optional[str] = None,
    de: Optional[datetime] = Query(default=None, description="Filtro de data de emissão (ISO8601)"),
    ate: Optional[datetime] = Query(default=None, description="Filtro de data de emissão (ISO8601)"),
    emit_cnpj: Optional[str] = Query(default=None, description="CNPJ do emitente"),
    dest_cnpj: Optional[str] = Query(default=None, description="CNPJ do destinatário"),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")
    q = _filtra_documentos(db, empresa_id, modelo, tipo, de, ate, emit_cnpj, dest_cnpj)
    return q.order_by(Documento.capturado_em.desc()).offset(offset).limit(limit).all()


@router.get("/empresas/{empresa_id}/documentos/exportar-csv")
def exportar_documentos_csv(
    empresa_id: str,
    modelo: Optional[str] = None,
    tipo: Optional[str] = None,
    de: Optional[datetime] = Query(default=None),
    ate: Optional[datetime] = Query(default=None),
    emit_cnpj: Optional[str] = Query(default=None),
    dest_cnpj: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Exporta os documentos filtrados em CSV (abre no Excel)."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")
    docs = (
        _filtra_documentos(db, empresa_id, modelo, tipo, de, ate, emit_cnpj, dest_cnpj)
        .order_by(Documento.dh_emissao.desc())
        .all()
    )
    import csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf, delimiter=";")
    w.writerow(["Modelo", "Tipo", "Numero", "Serie", "Situacao", "Rz Emitente",
                "CNPJ Emit", "CNPJ Dest", "Data Emissao", "Valor", "Capturado em", "Chave"])
    for d in docs:
        w.writerow([
            d.modelo, d.tipo, d.numero or "", d.serie or "", d.situacao or "",
            d.emit_razao_social or "", d.emit_cnpj or "", d.dest_cnpj or "",
            d.dh_emissao.strftime("%d/%m/%Y") if d.dh_emissao else "",
            (f"{float(d.valor_total):.2f}".replace(".", ",") if d.valor_total is not None else ""),
            d.capturado_em.strftime("%d/%m/%Y %H:%M") if d.capturado_em else "",
            d.chave or "",
        ])
    # BOM para o Excel reconhecer UTF-8 com acentos
    content = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="documentos.csv"'},
    )


@router.get("/empresas/{empresa_id}/documentos/{doc_id}", response_model=DocumentoOut)
def buscar_documento(empresa_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = db.get(Documento, doc_id)
    if not doc or doc.empresa_id != empresa_id:
        raise HTTPException(404, "Documento não encontrado")
    return doc


@router.get("/empresas/{empresa_id}/documentos/{doc_id}/xml")
def download_xml_por_id(
    empresa_id: str,
    doc_id: str,
    inline: bool = Query(False, description="true = abre no navegador; false = baixa"),
    db: Session = Depends(get_db),
):
    """Retorna o XML bruto do documento. `inline=true` abre no navegador."""
    doc = db.get(Documento, doc_id)
    if not doc or doc.empresa_id != empresa_id:
        raise HTTPException(404, "Documento não encontrado")
    try:
        xml_bytes = load_xml_doc(doc)
    except FileNotFoundError:
        raise HTTPException(404, "XML não disponível para este documento")
    filename = f"{doc.chave or doc_id}.xml"
    disp = "inline" if inline else "attachment"
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


@router.get("/documentos/chave/{chave}/xml")
def download_xml_por_chave(chave: str, db: Session = Depends(get_db)):
    """Retorna o XML bruto buscando pela chave do documento."""
    doc = db.query(Documento).filter_by(chave=chave).first()
    if not doc:
        raise HTTPException(404, "Documento não encontrado")
    try:
        xml_bytes = load_xml_doc(doc)
    except FileNotFoundError:
        raise HTTPException(404, "XML não disponível")
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{chave}.xml"'},
    )


# ---- Exportação ZIP mensal --------------------------------------------------

@router.get("/empresas/{empresa_id}/exportar")
def exportar_zip(
    empresa_id: str,
    mes: Optional[str] = Query(default=None, description="Mês no formato YYYY-MM (ex: 2026-05)"),
    de: Optional[datetime] = Query(default=None),
    ate: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Exporta ZIP com todos os XMLs do período. Use `mes` (YYYY-MM) ou `de`/`ate`."""
    empresa = db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(404, "Empresa não encontrada")

    if mes:
        try:
            ano, m = mes.split("-")
            from datetime import timezone as tz
            de = datetime(int(ano), int(m), 1, tzinfo=timezone.utc)
            import calendar
            ultimo_dia = calendar.monthrange(int(ano), int(m))[1]
            ate = datetime(int(ano), int(m), ultimo_dia, 23, 59, 59, tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(422, "Formato de mes inválido. Use YYYY-MM")

    if not de or not ate:
        raise HTTPException(422, "Informe mes (YYYY-MM) ou de+ate")

    q = (
        db.query(Documento)
        .filter_by(empresa_id=empresa_id)
        .filter((Documento.xml_gz.isnot(None)) | (Documento.storage_key.isnot(None)))
        .filter(Documento.dh_emissao >= de)
        .filter(Documento.dh_emissao <= ate)
        .order_by(Documento.dh_emissao)
    )
    docs = q.all()

    if not docs:
        raise HTTPException(404, "Nenhum documento encontrado no período")

    buf = io.BytesIO()
    erros = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            try:
                xml_bytes = load_xml_doc(doc)
                nome = f"{doc.modelo}/{doc.chave or doc.id}.xml"
                zf.writestr(nome, xml_bytes)
            except Exception:
                erros += 1

    buf.seek(0)
    periodo = mes or f"{de.date()}_{ate.date()}"
    filename = f"flua_{empresa.cnpj}_{periodo}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Total-Docs": str(len(docs)),
        "X-Erros": str(erros),
    }
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


# ---- Dashboard de saúde -----------------------------------------------------

@router.get("/empresas/{empresa_id}/saude")
def dashboard_saude(empresa_id: str, db: Session = Depends(get_db)):
    """Retorna status operacional: NSUs, distribuição, último log por modelo."""
    empresa = db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(404, "Empresa não encontrada")

    estados = db.query(DistribuicaoEstado).filter_by(empresa_id=empresa_id).all()

    # último log de captura por modelo
    from sqlalchemy import func as sqlfunc
    logs_q = (
        db.query(CapturaLog)
        .filter_by(empresa_id=empresa_id)
        .order_by(CapturaLog.ocorrido_em.desc())
        .limit(10)
        .all()
    )

    total_docs = db.query(Documento).filter_by(empresa_id=empresa_id).count()
    total_completos = db.query(Documento).filter_by(empresa_id=empresa_id, tipo="completo").count()

    alertas = alertas_empresa(db, empresa_id)

    return {
        "empresa_id": empresa_id,
        "cnpj": empresa.cnpj,
        "ativo": empresa.ativo,
        "total_documentos": total_docs,
        "total_completos": total_completos,
        "alertas_ativos": len(alertas),
        "distribuicao": [
            {
                "modelo": e.modelo,
                "tipo_fluxo": e.tipo_fluxo,
                "status": e.status,
                "ult_nsu": e.ult_nsu,
                "max_nsu": e.max_nsu,
                "gap_nsu": max(0, e.max_nsu - e.ult_nsu),
                "ultimo_sucesso": e.ultimo_sucesso,
                "proximo_polling": e.proximo_polling,
                "bloqueado_ate": e.bloqueado_ate,
            }
            for e in estados
        ],
        "ultimos_logs": [
            {
                "modelo": l.modelo,
                "tipo_consulta": l.tipo_consulta,
                "cstat": l.cstat,
                "xmotivo": l.xmotivo,
                "qtd_docs": l.qtd_docs,
                "latencia_ms": l.latencia_ms,
                "ocorrido_em": l.ocorrido_em,
            }
            for l in logs_q
        ],
        "alertas": alertas,
    }


# ---- Alertas ---------------------------------------------------------------

@router.get("/empresas/{empresa_id}/alertas")
def listar_alertas(empresa_id: str, db: Session = Depends(get_db)):
    """Retorna alertas operacionais ativos para a empresa."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")
    return {"empresa_id": empresa_id, "alertas": alertas_empresa(db, empresa_id)}


# ---- Métricas ---------------------------------------------------------------

@router.get("/empresas/{empresa_id}/metricas")
def metricas_captura(
    empresa_id: str,
    modelo: Optional[str] = None,
    ultimas_horas: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """Métricas de captura: latência, taxa de sucesso, volume por cstat."""
    if not db.get(Empresa, empresa_id):
        raise HTTPException(404, "Empresa não encontrada")

    desde = datetime.now(timezone.utc) - timedelta(hours=ultimas_horas)

    q = (
        db.query(CapturaLog)
        .filter_by(empresa_id=empresa_id)
        .filter(CapturaLog.ocorrido_em >= desde)
    )
    if modelo:
        q = q.filter_by(modelo=modelo)

    logs = q.all()

    if not logs:
        return {
            "empresa_id": empresa_id,
            "periodo_horas": ultimas_horas,
            "total_requisicoes": 0,
            "por_cstat": {},
            "por_modelo": {},
            "latencia": {},
            "documentos_capturados": 0,
        }

    # Agrupamentos
    por_cstat: Dict[str, int] = {}
    por_modelo: Dict[str, int] = {}
    latencias = [l.latencia_ms for l in logs if l.latencia_ms is not None]
    docs_total = sum(l.qtd_docs or 0 for l in logs)

    for l in logs:
        k = str(l.cstat or "?")
        por_cstat[k] = por_cstat.get(k, 0) + 1
        m = l.modelo or "?"
        por_modelo[m] = por_modelo.get(m, 0) + 1

    latencia_stats = {}
    if latencias:
        latencias_sorted = sorted(latencias)
        n = len(latencias_sorted)
        latencia_stats = {
            "min_ms": latencias_sorted[0],
            "max_ms": latencias_sorted[-1],
            "media_ms": round(sum(latencias_sorted) / n),
            "p50_ms": latencias_sorted[n // 2],
            "p95_ms": latencias_sorted[min(int(n * 0.95), n - 1)],
        }

    return {
        "empresa_id": empresa_id,
        "periodo_horas": ultimas_horas,
        "total_requisicoes": len(logs),
        "por_cstat": por_cstat,
        "por_modelo": por_modelo,
        "latencia": latencia_stats,
        "documentos_capturados": docs_total,
    }
