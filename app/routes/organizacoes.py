"""Gerenciamento de API keys e webhooks por organização."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, WebhookConfig
from app.services.auth import gerar_api_key

router = APIRouter(prefix="/organizacoes", tags=["organizacoes"])


# ---- schemas ----------------------------------------------------------------

class ApiKeyCreate(BaseModel):
    nome: str


class ApiKeyOut(BaseModel):
    id: str
    organizacao_id: str
    nome: str
    ativo: bool
    criado_em: datetime
    # raw_key só retornado na criação; None em listagens
    raw_key: Optional[str] = None

    model_config = {"from_attributes": True}


class WebhookCreate(BaseModel):
    url: str
    eventos: str = "documento.capturado,empresa.bloqueada_656"


class WebhookOut(BaseModel):
    id: str
    organizacao_id: str
    url: str
    eventos: str
    ativo: bool
    criado_em: datetime

    model_config = {"from_attributes": True}


# ---- API keys ---------------------------------------------------------------

@router.post("/{org_id}/api-keys", response_model=ApiKeyOut, status_code=201)
def criar_api_key(org_id: str, body: ApiKeyCreate, db: Session = Depends(get_db)):
    """Cria uma nova API key para a organização.

    A `raw_key` é retornada APENAS nesta resposta. Armazene-a com segurança.
    """
    raw, h = gerar_api_key()
    key = ApiKey(organizacao_id=org_id, nome=body.nome, chave_hash=h)
    db.add(key)
    db.commit()
    db.refresh(key)
    out = ApiKeyOut.model_validate(key)
    out.raw_key = raw
    return out


@router.get("/{org_id}/api-keys", response_model=List[ApiKeyOut])
def listar_api_keys(org_id: str, db: Session = Depends(get_db)):
    return db.query(ApiKey).filter_by(organizacao_id=org_id).all()


@router.delete("/{org_id}/api-keys/{key_id}", status_code=204)
def revogar_api_key(org_id: str, key_id: str, db: Session = Depends(get_db)):
    key = db.get(ApiKey, key_id)
    if not key or key.organizacao_id != org_id:
        raise HTTPException(404, "API key não encontrada")
    key.ativo = False
    db.commit()


# ---- Webhooks ---------------------------------------------------------------

@router.post("/{org_id}/webhooks", response_model=WebhookOut, status_code=201)
def criar_webhook(org_id: str, body: WebhookCreate, db: Session = Depends(get_db)):
    wh = WebhookConfig(organizacao_id=org_id, url=body.url, eventos=body.eventos)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@router.get("/{org_id}/webhooks", response_model=List[WebhookOut])
def listar_webhooks(org_id: str, db: Session = Depends(get_db)):
    return db.query(WebhookConfig).filter_by(organizacao_id=org_id).all()


@router.delete("/{org_id}/webhooks/{wh_id}", status_code=204)
def remover_webhook(org_id: str, wh_id: str, db: Session = Depends(get_db)):
    wh = db.get(WebhookConfig, wh_id)
    if not wh or wh.organizacao_id != org_id:
        raise HTTPException(404, "Webhook não encontrado")
    wh.ativo = False
    db.commit()
