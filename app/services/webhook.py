"""Disparo de eventos webhook por organização.

Cada evento é disparado em thread separada (fire-and-forget) com até
3 tentativas e backoff exponencial. Não bloqueia o fluxo principal.

Assinatura HMAC-SHA256: quando o WebhookConfig tiver campo `secret`,
o header `X-Flua-Signature` é adicionado com o valor
`sha256=<hmac-hex>` do body JSON. O receptor deve validar esse header.
"""

import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.models import Documento, WebhookConfig

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_TIMEOUT = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sign_payload(body: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _dispatch_one(url: str, payload: Dict[str, Any], secret: Optional[str] = None) -> None:
    body = json.dumps(payload, default=str).encode()
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["X-Flua-Signature"] = _sign_payload(body, secret)

    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(url, content=body, headers=headers)
            if resp.status_code < 500:
                return  # sucesso ou erro do cliente (não retentar 4xx)
            logger.warning("Webhook %s retornou %s (tentativa %d)", url, resp.status_code, attempt + 1)
        except Exception as exc:
            logger.warning("Webhook %s erro (tentativa %d): %s", url, attempt + 1, exc)
        if attempt < _MAX_RETRIES - 1:
            time.sleep(2 ** (attempt + 1))


def _load_configs(db: Session, organizacao_id: str, evento: str) -> List[WebhookConfig]:
    configs = (
        db.query(WebhookConfig)
        .filter_by(organizacao_id=organizacao_id, ativo=True)
        .all()
    )
    return [c for c in configs if evento in (c.eventos or "").split(",")]


def _fire(configs: List[WebhookConfig], payload: Dict[str, Any]) -> None:
    """Dispara para cada config em thread daemon independente."""
    for cfg in configs:
        t = threading.Thread(
            target=_dispatch_one,
            args=(cfg.url, payload, cfg.secret),
            daemon=True,
        )
        t.start()


def evento_documento_capturado(
    db: Session,
    organizacao_id: str,
    empresa_id: str,
    doc: "Documento",
) -> None:
    """Dispara evento documento.capturado com payload enriquecido."""
    configs = _load_configs(db, organizacao_id, "documento.capturado")
    if not configs:
        return

    import json as _json

    payload = {
        "evento": "documento.capturado",
        "ocorrido_em": _now_iso(),
        "data": {
            "empresa_id": empresa_id,
            "documento_id": doc.id,
            "modelo": doc.modelo,
            "tipo": doc.tipo,
            "direcao": getattr(doc, "direcao", "entrada"),  # entrada | saida
            "chave": doc.chave,
            "situacao": doc.situacao,
            "valor_total": float(doc.valor_total) if doc.valor_total is not None else None,
            "dh_emissao": doc.dh_emissao.isoformat() if doc.dh_emissao else None,
            # Emitente
            "emit_cnpj": doc.emit_cnpj,
            "emit_razao_social": doc.emit_razao_social,
            "emit_ie": doc.emit_ie,
            "emit_xlogradouro": doc.emit_xlogradouro,
            "emit_xmun": doc.emit_xmun,
            "emit_uf": doc.emit_uf,
            "emit_cep": doc.emit_cep,
            # Destinatário
            "dest_cnpj": doc.dest_cnpj,
            # Número/série
            "numero": doc.numero,
            "serie": doc.serie,
            # Totais fiscais
            "v_prod": float(doc.v_prod) if doc.v_prod is not None else None,
            "v_frete": float(doc.v_frete) if doc.v_frete is not None else None,
            "v_seg": float(doc.v_seg) if doc.v_seg is not None else None,
            "v_desc": float(doc.v_desc) if doc.v_desc is not None else None,
            "v_ipi": float(doc.v_ipi) if doc.v_ipi is not None else None,
            "v_icms": float(doc.v_icms) if doc.v_icms is not None else None,
            "v_pis": float(doc.v_pis) if doc.v_pis is not None else None,
            "v_cofins": float(doc.v_cofins) if doc.v_cofins is not None else None,
            # Itens e duplicatas
            "itens": _json.loads(doc.itens_json) if doc.itens_json else [],
            "duplicatas": _json.loads(doc.duplicatas_json) if doc.duplicatas_json else [],
        },
    }
    _fire(configs, payload)


def evento_certificado_expirando(
    db: Session,
    organizacao_id: str,
    empresa_id: str,
    cnpj: str,
    fingerprint: Optional[str],
    valido_ate: datetime,
    dias_restantes: int,
) -> None:
    configs = _load_configs(db, organizacao_id, "certificado.expirando")
    if not configs:
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
    _fire(configs, payload)


def evento_empresa_bloqueada_656(
    db: Session,
    organizacao_id: str,
    empresa_id: str,
    modelo: str,
    tipo_fluxo: str,
    xmotivo: str,
) -> None:
    configs = _load_configs(db, organizacao_id, "empresa.bloqueada_656")
    if not configs:
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
    _fire(configs, payload)
