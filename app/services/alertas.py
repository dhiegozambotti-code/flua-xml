"""Serviço de alertas operacionais.

Detecta condições de alerta em todas as empresas ativas:
- certificado.expirando  (D-30, D-7, D-1)
- distribuicao.bloqueada_656
- distribuicao.cert_invalido
- distribuicao.sem_polling (gap > 2h sem sucesso enquanto ativo)

Também fornece a função `alertas_empresa` para o endpoint REST.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models import Certificado, DistribuicaoEstado, Empresa

logger = logging.getLogger(__name__)

# Limites de alerta para expiração de certificado (dias)
_DIAS_ALERTA = (30, 7, 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---- Verificação de certificados expirando ----------------------------------

def sweep_certificados_expirando(db: Session) -> None:
    """Varre todos os certificados ativos e dispara webhook nos marcos D-30/D-7/D-1."""
    from app.services.webhook import evento_certificado_expirando

    agora = _now()
    certs = (
        db.query(Certificado)
        .filter_by(status="ativo")
        .all()
    )
    for cert in certs:
        if not cert.valido_ate:
            continue
        valido_ate = _aware(cert.valido_ate)
        dias = (valido_ate - agora).days
        if dias in _DIAS_ALERTA:
            empresa = db.get(Empresa, cert.empresa_id)
            if not empresa or not empresa.ativo:
                continue
            logger.warning(
                "Certificado expirando em %d dia(s): empresa=%s fingerprint=%s",
                dias, cert.empresa_id, cert.fingerprint,
            )
            try:
                evento_certificado_expirando(
                    db=db,
                    organizacao_id=empresa.organizacao_id,
                    empresa_id=empresa.id,
                    cnpj=empresa.cnpj,
                    fingerprint=cert.fingerprint,
                    valido_ate=valido_ate,
                    dias_restantes=dias,
                )
            except Exception:
                logger.exception("Falha ao disparar webhook certificado.expirando")


# ---- Alertas por empresa (para endpoint REST) --------------------------------

def alertas_empresa(db: Session, empresa_id: str) -> List[Dict[str, Any]]:
    """Retorna lista de alertas ativos para a empresa."""
    agora = _now()
    alertas: List[Dict[str, Any]] = []

    # ---- Certificados
    certs = db.query(Certificado).filter_by(empresa_id=empresa_id).all()
    tem_cert_ativo = False
    for cert in certs:
        if cert.status != "ativo":
            alertas.append({
                "tipo": "certificado.inativo",
                "severidade": "critico",
                "mensagem": f"Certificado {cert.fingerprint or cert.id} com status '{cert.status}'",
                "detalhe": {"certificado_id": cert.id, "fingerprint": cert.fingerprint},
            })
            continue

        tem_cert_ativo = True
        if cert.valido_ate:
            valido_ate = _aware(cert.valido_ate)
            dias = (valido_ate - agora).days
            if dias < 0:
                alertas.append({
                    "tipo": "certificado.expirado",
                    "severidade": "critico",
                    "mensagem": f"Certificado expirou há {abs(dias)} dia(s)",
                    "detalhe": {
                        "certificado_id": cert.id,
                        "valido_ate": valido_ate.isoformat(),
                        "dias_restantes": dias,
                    },
                })
            elif dias <= 7:
                alertas.append({
                    "tipo": "certificado.expirando",
                    "severidade": "critico",
                    "mensagem": f"Certificado expira em {dias} dia(s)",
                    "detalhe": {
                        "certificado_id": cert.id,
                        "valido_ate": valido_ate.isoformat(),
                        "dias_restantes": dias,
                    },
                })
            elif dias <= 30:
                alertas.append({
                    "tipo": "certificado.expirando",
                    "severidade": "aviso",
                    "mensagem": f"Certificado expira em {dias} dia(s)",
                    "detalhe": {
                        "certificado_id": cert.id,
                        "valido_ate": valido_ate.isoformat(),
                        "dias_restantes": dias,
                    },
                })

    if not tem_cert_ativo and not certs:
        alertas.append({
            "tipo": "certificado.ausente",
            "severidade": "critico",
            "mensagem": "Nenhum certificado cadastrado",
            "detalhe": {},
        })

    # ---- Distribuição
    estados = db.query(DistribuicaoEstado).filter_by(empresa_id=empresa_id).all()
    for estado in estados:
        label = f"{estado.modelo}/{estado.tipo_fluxo}"

        if estado.status == "bloqueado_656":
            bloqueado_ate = _aware(estado.bloqueado_ate) if estado.bloqueado_ate else None
            alertas.append({
                "tipo": "distribuicao.bloqueada_656",
                "severidade": "critico",
                "mensagem": f"CNPJ bloqueado por consumo indevido ({label})",
                "detalhe": {
                    "modelo": estado.modelo,
                    "tipo_fluxo": estado.tipo_fluxo,
                    "bloqueado_ate": bloqueado_ate.isoformat() if bloqueado_ate else None,
                },
            })

        elif estado.status == "cert_invalido":
            alertas.append({
                "tipo": "distribuicao.cert_invalido",
                "severidade": "critico",
                "mensagem": f"Certificado inválido para distribuição ({label})",
                "detalhe": {"modelo": estado.modelo, "tipo_fluxo": estado.tipo_fluxo},
            })

        elif estado.status == "ativo" and estado.ultimo_sucesso:
            ultimo = _aware(estado.ultimo_sucesso)
            gap = agora - ultimo
            if gap > timedelta(hours=2):
                horas = int(gap.total_seconds() // 3600)
                alertas.append({
                    "tipo": "distribuicao.sem_polling",
                    "severidade": "aviso",
                    "mensagem": f"Sem captura há {horas}h ({label})",
                    "detalhe": {
                        "modelo": estado.modelo,
                        "tipo_fluxo": estado.tipo_fluxo,
                        "ultimo_sucesso": ultimo.isoformat(),
                        "horas_sem_captura": horas,
                    },
                })

    return alertas
