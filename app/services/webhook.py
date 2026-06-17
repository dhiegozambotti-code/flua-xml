"""Disparo de eventos webhook por organização.

Cada evento é disparado em thread separada (fire-and-forget) com até
3 tentativas e backoff exponencial. Não bloqueia o fluxo principal.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.models import WebhookConfig

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_TIMEOUT = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dispatch_one(url: str, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, default=str).encode()
    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(
                    url,
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
            if resp.status_code < 500:
                return  # sucesso ou erro do cliente (não retentar 4xx)
            logger.warning("Webhook %s retornou %s (tentativa %d)", url, resp.status_code, attempt + 1)
        except Exception as exc:
            logger.warning("Webhook %s erro (tentativa %d): %s", url, attempt + 1, exc)
        if attempt < _MAX_RETRIES - 1:
            time.sleep(2 ** (attempt + 1))


def _load_urls(db: Session, organizacao_id: str, evento: str) -> List[str]:
    configs = (
        db.query(WebhookConfig)
        .filter_by(organizacao_id=organizacao_id, ativo=True)
        .all()
    )
    return [
        c.url for c in configs
        if evento in (c.eventos or "").split(",")
    ]


def _fire(urls: List[str], payload: Dict[str, Any]) -> None:
    """Dispara para cada URL em thread daemon independente."""
    for url in urls:
        t = threading.Thread(target=_dispatch_one, args=(url, payload), daemon=True)
        t.start()


def evento_documento_capturado(
    db: Session,
    organizacao_id: str,
    empresa_id: str,
    doc_id: str,
    modelo: str,
    tipo: str,
    chave: Optional[str],
    valor_total: Optional[float],
) -> None:
    urls = _load_urls(db, organizacao_id, "documento.capturado")
    if not urls:
        return
    payload = {
        "evento": "documento.capturado",
        "ocorrido_em": _now_iso(),
        "data": {
            "empresa_id": empresa_id,
            "documento_id": doc_id,
            "modelo": modelo,
            "tipo": tipo,
            "chave": chave,
            "valor_total": valor_total,
        },
    }
    _fire(urls, payload)


def evento_certificado_expirando(
    db: Session,
    organizacao_id: str,
    empresa_id: str,
    cnpj: str,
    fingerprint: Optional[str],
    valido_ate: datetime,
    dias_restantes: int,
) -> None:
    urls = _load_urls(db, organizacao_id, "certificado.expirando")
    if not urls:
        return
    payload = {
        "evento": "certificado.expirando",
        "ocorrido_em": _now_iso(),
        "data": {
            "empresa_id": empresa_id,
            "cnpj": cnpj,
            "fingerprint": fingerprint,
            "valido_ate": valido_ate.isoformat() if valido_ate else None,
            "dias_restantes": dias_restantes,
        },
    }
    _fire(urls, payload)


def evento_empresa_bloqueada_656(
    db: Session,
    organizacao_id: str,
    empresa_id: str,
    modelo: str,
    tipo_fluxo: str,
    xmotivo: str,
) -> None:
    urls = _load_urls(db, organizacao_id, "empresa.bloqueada_656")
    if not urls:
        return
    payload = {
        "evento": "empresa.bloqueada_656",
        "ocorrido_em": _now_iso(),
        "data": {
            "empresa_id": empresa_id,
            "modelo": modelo,
            "tipo_fluxo": tipo_fluxo,
            "xmotivo": xmotivo,
        },
    }
    _fire(urls, payload)
