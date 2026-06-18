"""Endpoints de consulta de documentos capturados.

Usados pelo ERP Flua para buscar detalhes de NF-e após receber um webhook.
"""

import base64
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Documento
from app.services.auth import get_organizacao_id as require_api_key
from app.services.storage import load_xml_doc

router = APIRouter(prefix="/documentos", tags=["documentos"])


class DocumentoOut(BaseModel):
    id: str
    empresa_id: str
    modelo: str
    tipo: str
    nsu: int
    chave: Optional[str]
    situacao: Optional[str]
    numero: Optional[str]
    serie: Optional[str]
    emit_cnpj: Optional[str]
    emit_razao_social: Optional[str]
    emit_ie: Optional[str]
    emit_xlogradouro: Optional[str]
    emit_xmun: Optional[str]
    emit_uf: Optional[str]
    emit_cep: Optional[str]
    dest_cnpj: Optional[str]
    valor_total: Optional[float]
    v_prod: Optional[float]
    v_frete: Optional[float]
    v_seg: Optional[float]
    v_desc: Optional[float]
    v_ipi: Optional[float]
    v_icms: Optional[float]
    v_pis: Optional[float]
    v_cofins: Optional[float]
    dh_emissao: Optional[str]
    itens: Optional[list]
    duplicatas: Optional[list]
    xml_b64: Optional[str]
    storage_key: Optional[str]
    sha256: Optional[str]

    model_config = {"from_attributes": True}


@router.get("", response_model=List[DocumentoOut])
def listar_documentos(
    empresa_id: Optional[str] = Query(None),
    modelo: Optional[str] = Query(None),
    situacao: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    q = db.query(Documento)
    if empresa_id:
        q = q.filter_by(empresa_id=empresa_id)
    if modelo:
        q = q.filter_by(modelo=modelo)
    if situacao:
        q = q.filter_by(situacao=situacao)
    docs = q.order_by(Documento.capturado_em.desc()).offset(offset).limit(limit).all()
    return [_to_out(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentoOut)
def buscar_documento(
    doc_id: str,
    include_xml: bool = Query(False),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    doc = db.get(Documento, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return _to_out(doc, include_xml=include_xml)


def _to_out(doc: Documento, include_xml: bool = False) -> DocumentoOut:
    xml_b64 = None
    if include_xml:
        try:
            xml_bytes = load_xml_doc(doc)
            xml_b64 = base64.b64encode(xml_bytes).decode()
        except Exception:
            pass

    return DocumentoOut(
        id=doc.id,
        empresa_id=doc.empresa_id,
        modelo=doc.modelo,
        tipo=doc.tipo,
        nsu=doc.nsu,
        chave=doc.chave,
        situacao=doc.situacao,
        numero=doc.numero,
        serie=doc.serie,
        emit_cnpj=doc.emit_cnpj,
        emit_razao_social=doc.emit_razao_social,
        emit_ie=doc.emit_ie,
        emit_xlogradouro=doc.emit_xlogradouro,
        emit_xmun=doc.emit_xmun,
        emit_uf=doc.emit_uf,
        emit_cep=doc.emit_cep,
        dest_cnpj=doc.dest_cnpj,
        valor_total=float(doc.valor_total) if doc.valor_total is not None else None,
        v_prod=float(doc.v_prod) if doc.v_prod is not None else None,
        v_frete=float(doc.v_frete) if doc.v_frete is not None else None,
        v_seg=float(doc.v_seg) if doc.v_seg is not None else None,
        v_desc=float(doc.v_desc) if doc.v_desc is not None else None,
        v_ipi=float(doc.v_ipi) if doc.v_ipi is not None else None,
        v_icms=float(doc.v_icms) if doc.v_icms is not None else None,
        v_pis=float(doc.v_pis) if doc.v_pis is not None else None,
        v_cofins=float(doc.v_cofins) if doc.v_cofins is not None else None,
        dh_emissao=doc.dh_emissao.isoformat() if doc.dh_emissao else None,
        itens=json.loads(doc.itens_json) if doc.itens_json else [],
        duplicatas=json.loads(doc.duplicatas_json) if doc.duplicatas_json else [],
        xml_b64=xml_b64,
        storage_key=doc.storage_key,
        sha256=doc.sha256,
    )
