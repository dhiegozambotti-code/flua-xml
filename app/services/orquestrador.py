"""Motor de orquestração NSU.

Implementa o loop de polling por (empresa × modelo × tipo_fluxo) com:
- Lock advisory do Postgres (uma execução por vez por empresa×modelo×fluxo)
- Máquina de estados: ativo → sem_documentos / bloqueado_656 / cert_invalido
- Regra crítica cStat=137: next_poll = now + 1h
- Regra crítica cStat=656: bloqueio imediato, sem retry
- Backoff exponencial em erros temporários
- Auto-enfileiramento de Manifestação 210210 em resumos de entrada
"""

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CapturaLog, Certificado, DistribuicaoEstado, Documento, Empresa
from app.services.crypto import decrypt_bytes
from app.services.parser import parse_doczip
from app.services.sefaz_client import NFeSoapClient
from app.services.storage import save_xml

logger = logging.getLogger(__name__)


def _to_decimal(val) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except InvalidOperation:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _advisory_key(empresa_id: str, modelo: str, tipo_fluxo: str) -> int:
    """Gera chave bigint estável para pg_advisory_lock."""
    import ctypes
    s = f"{empresa_id}:{modelo}:{tipo_fluxo}".encode()
    h = hash(s) & 0x7FFFFFFFFFFFFFFF
    return ctypes.c_longlong(h).value


@contextmanager
def _pg_try_lock(db: Session, key: int):
    """Tenta adquirir advisory lock; libera ao sair do contexto."""
    row = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
    acquired = bool(row)
    try:
        yield acquired
    finally:
        if acquired:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})


def _get_estado(db: Session, empresa_id: str, modelo: str, tipo_fluxo: str = "entrada"):
    return (
        db.query(DistribuicaoEstado)
        .filter_by(empresa_id=empresa_id, modelo=modelo, tipo_fluxo=tipo_fluxo)
        .first()
    )


def _log_captura(db: Session, empresa_id: str, modelo: str, tipo: str,
                 cstat: int, xmotivo: str, qtd: int, latencia_ms: int):
    entry = CapturaLog(
        empresa_id=empresa_id,
        modelo=modelo,
        tipo_consulta=tipo,
        cstat=cstat,
        xmotivo=xmotivo,
        qtd_docs=qtd,
        latencia_ms=latencia_ms,
    )
    db.add(entry)
    db.commit()


def _doc_exists(db: Session, empresa_id: str, modelo: str, nsu: int, chave: Optional[str]) -> bool:
    q = db.query(Documento).filter_by(empresa_id=empresa_id, modelo=modelo, nsu=nsu)
    if q.first():
        return True
    if chave:
        q2 = db.query(Documento).filter_by(empresa_id=empresa_id, chave=chave)
        if q2.first():
            return True
    return False


def _store_doc(db: Session, empresa_id: str, modelo: str, nsu: int, parsed: dict):
    chave = parsed.get("chave") or ""
    xml_bytes = parsed.get("xml_bytes", b"")

    # Usa modelo_doc do parser (detecta nfce/nfe dentro do procNFe)
    modelo_efetivo = parsed.get("modelo_doc") or modelo

    storage_key = None
    if xml_bytes and chave:
        try:
            storage_key = save_xml(empresa_id, modelo_efetivo, chave, xml_bytes)
        except Exception as exc:
            logger.warning("Falha ao salvar XML em disco (nsu=%s): %s", nsu, exc)

    # Persistência durável: XML comprimido no Postgres (imune a redeploys)
    xml_gz = None
    if xml_bytes:
        import gzip
        try:
            xml_gz = gzip.compress(xml_bytes)
        except Exception as exc:
            logger.warning("Falha ao comprimir XML (nsu=%s): %s", nsu, exc)

    try:
        valor = Decimal(str(parsed["valor_total"])) if parsed.get("valor_total") else None
    except InvalidOperation:
        valor = None

    dh = None
    if parsed.get("dh_emissao"):
        try:
            from dateutil import parser as dparse
            dh = dparse.parse(parsed["dh_emissao"])
        except Exception:
            pass

    doc = Documento(
        empresa_id=empresa_id,
        modelo=modelo_efetivo,
        tipo=parsed.get("tipo", "desconhecido"),
        nsu=nsu,
        schema_xsd=parsed.get("schema_xsd"),
        chave=chave or None,
        emit_cnpj=parsed.get("emit_cnpj"),
        dest_cnpj=parsed.get("dest_cnpj"),
        valor_total=valor,
        dh_emissao=dh,
        situacao=parsed.get("situacao"),
        storage_key=storage_key,
        xml_gz=xml_gz,
        sha256=parsed.get("sha256"),
        # CT-e
        modal=parsed.get("modal"),
        tomador=parsed.get("tomador"),
        rem_cnpj=parsed.get("rem_cnpj"),
        rec_cnpj=parsed.get("rec_cnpj"),
        # IBSCBS — Reforma Tributária NT 2026.001
        ibscbs_cst=parsed.get("ibscbs", {}) and parsed["ibscbs"].get("cst") if parsed.get("ibscbs") else None,
        ibscbs_cclass_trib=parsed.get("ibscbs", {}) and parsed["ibscbs"].get("cclass_trib") if parsed.get("ibscbs") else None,
        ibscbs_nbs=parsed.get("ibscbs", {}) and parsed["ibscbs"].get("nbs") if parsed.get("ibscbs") else None,
        # MDF-e
        mdfe_uf_ini=parsed.get("mdfe_uf_ini"),
        mdfe_uf_fim=parsed.get("mdfe_uf_fim"),
        mdfe_qtd_cte=parsed.get("mdfe_qtd_cte"),
        mdfe_qtd_nfe=parsed.get("mdfe_qtd_nfe"),
        # Emitente — dados completos (NF-e)
        emit_razao_social=parsed.get("emit_razao_social"),
        emit_ie=parsed.get("emit_ie"),
        emit_xlogradouro=parsed.get("emit_xlogradouro"),
        emit_xmun=parsed.get("emit_xmun"),
        emit_uf=parsed.get("emit_uf"),
        emit_cep=parsed.get("emit_cep"),
        # Número/série NF-e
        numero=parsed.get("numero"),
        serie=parsed.get("serie"),
        # Totais fiscais NF-e
        v_prod=_to_decimal(parsed.get("v_prod")),
        v_frete=_to_decimal(parsed.get("v_frete")),
        v_seg=_to_decimal(parsed.get("v_seg")),
        v_desc=_to_decimal(parsed.get("v_desc")),
        v_ipi=_to_decimal(parsed.get("v_ipi")),
        v_icms=_to_decimal(parsed.get("v_icms")),
        v_pis=_to_decimal(parsed.get("v_pis")),
        v_cofins=_to_decimal(parsed.get("v_cofins")),
        # Itens e duplicatas JSON
        itens_json=parsed.get("itens_json"),
        duplicatas_json=parsed.get("duplicatas_json"),
    )
    db.add(doc)
    db.commit()
    return doc


def _auto_manifestar(db: Session, empresa_id: str, empresa_cnpj: str, parsed: dict):
    """Enfileira Manifestação 210210 para resumos de entrada destinados a esta empresa."""
    if not settings.auto_manifestacao_habilitado:
        return
    if parsed.get("tipo") != "resumo":
        return
    chave = parsed.get("chave")
    if not chave:
        return
    # Só manifesta se esta empresa é o destinatário
    dest = parsed.get("dest_cnpj") or ""
    if dest and dest != empresa_cnpj:
        return

    from app.services.manifestacao import enfileirar
    enfileirar(db, empresa_id, chave, settings.auto_manifestacao_tipo)
    logger.debug("Manifestação 210210 enfileirada para chave=%s", chave)


def _fire_webhook_captura(db: Session, empresa: Empresa, doc: Documento) -> None:
    try:
        from app.services.webhook import evento_documento_capturado
        evento_documento_capturado(
            db=db,
            organizacao_id=empresa.organizacao_id,
            empresa_id=empresa.id,
            doc=doc,
        )
    except Exception:
        logger.exception("Falha ao disparar webhook documento.capturado")


def _fire_webhook_656(db: Session, empresa: Empresa, estado: DistribuicaoEstado, xmotivo: str) -> None:
    try:
        from app.services.webhook import evento_empresa_bloqueada_656
        evento_empresa_bloqueada_656(
            db=db,
            organizacao_id=empresa.organizacao_id,
            empresa_id=empresa.id,
            modelo=estado.modelo,
            tipo_fluxo=estado.tipo_fluxo,
            xmotivo=xmotivo,
        )
    except Exception:
        logger.exception("Falha ao disparar webhook empresa.bloqueada_656")


def _poll_estado(db: Session, estado: DistribuicaoEstado, empresa: Empresa,
                 pfx_bytes: bytes, senha: str) -> None:
    """Ciclo de polling para um estado específico."""
    now = _now()

    if estado.proximo_polling and estado.proximo_polling.replace(tzinfo=timezone.utc) > now:
        return
    if estado.status == "bloqueado_656" and estado.bloqueado_ate:
        if estado.bloqueado_ate.replace(tzinfo=timezone.utc) > now:
            return
    if estado.status == "cert_invalido":
        return

    endpoint = settings.cte_endpoint if estado.modelo == "cte" else settings.nfe_endpoint
    client = NFeSoapClient(
        pfx_bytes=pfx_bytes,
        senha=senha,
        endpoint=endpoint,
        tp_amb=settings.tp_amb,
        modelo=estado.modelo,
    )
    estado.endpoint_usado = endpoint
    db.commit()

    # Loop de drenagem: enquanto o SEFAZ retornar cStat=138 com novos NSUs,
    # busca lotes consecutivos no mesmo ciclo (permitido enquanto há documentos).
    # Teto de segurança evita loop infinito caso ultNSU não avance.
    MAX_LOTES = 250  # ~12500 docs por ciclo
    for _lote in range(MAX_LOTES):
        # --- chamada SEFAZ com retry para erros transitórios ---
        resp = None
        for attempt in range(settings.polling_max_retries):
            t0 = time.time()
            try:
                resp = client.dist_nsu(
                    uf=empresa.uf or "SP",
                    cnpj=empresa.cnpj,
                    ult_nsu=estado.ult_nsu,
                )
                break
            except Exception as exc:
                latencia = int((time.time() - t0) * 1000)
                logger.warning(
                    "Erro na chamada SEFAZ (tentativa %d/%d) empresa=%s fluxo=%s: %s",
                    attempt + 1, settings.polling_max_retries,
                    estado.empresa_id, estado.tipo_fluxo, exc,
                )
                _log_captura(db, estado.empresa_id, estado.modelo, "distNSU", 0, str(exc), 0, latencia)
                if attempt < settings.polling_max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return
        if resp is None:
            return

        now = _now()
        latencia = int((time.time() - t0) * 1000)
        cstat = resp["cstat"]
        _log_captura(db, estado.empresa_id, estado.modelo, "distNSU", cstat,
                     resp["xmotivo"], len(resp["docs"]), latencia)

        if cstat == 138:
            nsu_anterior = estado.ult_nsu
            for doc_item in resp["docs"]:
                nsu = doc_item["nsu"]
                if _doc_exists(db, estado.empresa_id, estado.modelo, nsu, None):
                    logger.debug("NSU %s já existe; pulando", nsu)
                    continue
                try:
                    parsed = parse_doczip(doc_item["schema"], doc_item["b64"])
                    doc = _store_doc(db, estado.empresa_id, estado.modelo, nsu, parsed)
                    logger.info(
                        "Doc NSU=%s chave=%s tipo=%s fluxo=%s armazenado",
                        nsu, parsed.get("chave"), parsed.get("tipo"), estado.tipo_fluxo,
                    )
                    _fire_webhook_captura(db, empresa, doc)
                    # Auto-manifesta apenas em captura de entrada
                    if estado.tipo_fluxo == "entrada":
                        _auto_manifestar(db, estado.empresa_id, empresa.cnpj, parsed)
                except Exception as exc:
                    logger.error("Falha ao processar docZip NSU=%s: %s", nsu, exc)

            estado.ult_nsu = resp["ult_nsu"]
            estado.max_nsu = resp["max_nsu"]
            estado.status = "ativo"
            estado.ultimo_sucesso = now
            db.commit()

            # Caught up ou ultNSU não avançou (proteção contra loop) → encerra ciclo
            if estado.ult_nsu >= estado.max_nsu or estado.ult_nsu <= nsu_anterior:
                estado.proximo_polling = now + timedelta(hours=1)
                db.commit()
                break
            # Há mais documentos no backlog → busca o próximo lote imediatamente
            continue

        elif cstat == 137:
            estado.status = "sem_documentos"
            estado.proximo_polling = now + timedelta(hours=1)
            db.commit()
            logger.info(
                "cStat=137 para %s/%s/%s; próximo poll em %s",
                estado.empresa_id, estado.modelo, estado.tipo_fluxo, estado.proximo_polling,
            )
            break

        elif cstat == 656:
            # O SEFAZ reporta ultNSU/maxNSU mesmo no 656. Se a distribuição já foi
            # consumida antes (ultNSU > nosso ult_nsu), avançamos para a posição real —
            # pedir a partir de 0 é justamente o que dispara o "consumo indevido".
            sefaz_ult = resp.get("ult_nsu") or 0
            sefaz_max = resp.get("max_nsu") or 0
            if sefaz_ult > estado.ult_nsu:
                logger.warning(
                    "656 com ultNSU=%s > local=%s; avançando ponteiro para evitar re-consumo",
                    sefaz_ult, estado.ult_nsu,
                )
                estado.ult_nsu = sefaz_ult
                if sefaz_max:
                    estado.max_nsu = sefaz_max
            estado.status = "bloqueado_656"
            estado.bloqueado_ate = now + timedelta(hours=1)
            estado.proximo_polling = now + timedelta(hours=1)
            db.commit()
            logger.error(
                "BLOQUEIO 656 para %s/%s/%s até %s — motivo: %s",
                estado.empresa_id, estado.modelo, estado.tipo_fluxo,
                estado.bloqueado_ate, resp["xmotivo"],
            )
            _fire_webhook_656(db, empresa, estado, resp["xmotivo"])
            break

        else:
            logger.warning(
                "cStat inesperado %s para %s/%s/%s: %s",
                cstat, estado.empresa_id, estado.modelo, estado.tipo_fluxo, resp["xmotivo"],
            )
            break


def poll_empresa_modelo(db: Session, empresa_id: str, modelo: str,
                        tipo_fluxo: str = "entrada") -> None:
    """Executa um ciclo de polling para uma empresa×modelo×fluxo."""
    lock_key = _advisory_key(empresa_id, modelo, tipo_fluxo)
    with _pg_try_lock(db, lock_key) as acquired:
        if not acquired:
            logger.debug("Lock ocupado para %s/%s/%s; pulando", empresa_id, modelo, tipo_fluxo)
            return

        estado = _get_estado(db, empresa_id, modelo, tipo_fluxo)
        if estado is None:
            return

        cert = (
            db.query(Certificado)
            .filter_by(empresa_id=empresa_id, status="ativo")
            .order_by(Certificado.valido_ate.desc())
            .first()
        )
        if cert is None:
            logger.warning("Empresa %s sem certificado ativo", empresa_id)
            estado.status = "cert_invalido"
            db.commit()
            return

        now = _now()
        if cert.valido_ate and cert.valido_ate.replace(tzinfo=timezone.utc) < now:
            logger.warning("Certificado expirado para empresa %s", empresa_id)
            estado.status = "cert_invalido"
            db.commit()
            return

        try:
            pfx_bytes = decrypt_bytes(cert.pfx_cifrado, settings.vault_master_key_bytes)
            senha = decrypt_bytes(cert.senha_cifrada, settings.vault_master_key_bytes).decode()
        except Exception as exc:
            logger.error("Falha ao descriptografar cert empresa %s: %s", empresa_id, exc)
            estado.status = "cert_invalido"
            db.commit()
            return

        empresa = db.get(Empresa, empresa_id)
        if not empresa:
            return

        _poll_estado(db, estado, empresa, pfx_bytes, senha)


# Brasil não usa horário de verão desde 2019 → offset fixo UTC-3.
_BR_OFFSET = timedelta(hours=-3)


def dentro_janela_polling(empresa: Empresa, agora_utc: Optional[datetime] = None) -> bool:
    """Verifica se o horário atual (BRT) está dentro da janela de polling da empresa.

    Ambos os limites nulos (ou iguais) → 24h. Suporta janela que cruza a meia-noite
    (ex: inicio=20, fim=6 → das 20h às 6h).
    """
    ini = empresa.polling_janela_inicio
    fim = empresa.polling_janela_fim
    if ini is None or fim is None or ini == fim:
        return True
    agora_utc = agora_utc or _now()
    hora = (agora_utc + _BR_OFFSET).hour
    if ini < fim:
        return ini <= hora < fim
    # janela cruza a meia-noite
    return hora >= ini or hora < fim


def run_sweep(db: Session) -> None:
    """Varre todos os estados de distribuição elegíveis e processa manifestações pendentes."""
    from app.services.manifestacao import enviar_pendentes

    estados = (
        db.query(DistribuicaoEstado)
        .join(Empresa, DistribuicaoEstado.empresa_id == Empresa.id)
        .filter(Empresa.ativo.is_(True))
        # bloqueado_656 é incluído: _poll_estado verifica se o bloqueio já expirou
        # (sem isto, o estado ficaria preso para sempre após o bloqueio terminar)
        .filter(DistribuicaoEstado.status.in_(["ativo", "sem_documentos", "bloqueado_656"]))
        .all()
    )

    agora = _now()
    for estado in estados:
        # Respeita a janela de polling (consulta noturna) configurada na empresa
        empresa = db.get(Empresa, estado.empresa_id)
        if empresa and not dentro_janela_polling(empresa, agora):
            continue
        try:
            poll_empresa_modelo(
                db, estado.empresa_id, estado.modelo, estado.tipo_fluxo
            )
        except Exception:
            logger.exception(
                "Erro inesperado no poll de %s/%s/%s",
                estado.empresa_id, estado.modelo, estado.tipo_fluxo,
            )

    # Envia manifestações pendentes após processar todos os polls
    try:
        n = enviar_pendentes(db)
        if n:
            logger.info("%d manifestação(ões) enviada(s)", n)
    except Exception:
        logger.exception("Erro ao enviar manifestações pendentes")

    # Verifica certificados expirando (D-30, D-7, D-1)
    try:
        from app.services.alertas import sweep_certificados_expirando
        sweep_certificados_expirando(db)
    except Exception:
        logger.exception("Erro no sweep de certificados")
