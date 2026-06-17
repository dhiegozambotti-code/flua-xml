"""Autenticação por API key (X-API-Key header).

Fluxo: ERP envia X-API-Key → sha256 da chave é buscado na tabela api_key
→ retorna organizacao_id. Chaves são geradas aleatoriamente e nunca
armazenadas em claro — apenas o hash SHA-256.
"""

import hashlib
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def gerar_api_key() -> tuple:
    """Gera (raw_key, hash). raw_key é retornado apenas uma vez."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash_key(raw)


def get_organizacao_id(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> str:
    """Dependency: valida X-API-Key e retorna organizacao_id."""
    if not x_api_key:
        raise HTTPException(401, "X-API-Key ausente")
    h = _hash_key(x_api_key)
    key = db.query(ApiKey).filter_by(chave_hash=h, ativo=True).first()
    if not key:
        raise HTTPException(401, "API key inválida ou inativa")
    return key.organizacao_id
