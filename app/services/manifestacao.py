"""Manifestação do Destinatário (MDe) — NFeRecepcaoEvento.

Tipos de evento:
  210200 — Confirmação da Operação
  210210 — Ciência da Operação  (padrão automático Flua-XML)
  210220 — Desconhecimento da Operação
  210240 — Operação não Realizada

Fluxo:
  1. Orquestrador detecta resNFe de entrada → enfileira 210210 (status=pendente)
  2. Worker chama enviar_pendentes() → assina XML → POST mTLS → grava protocolo
  3. Próximo ciclo de distNSU entrega procNFe completo (chave agora manifestada)
"""

import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from lxml import etree
from signxml import XMLSigner, methods

from app.config import settings
from app.models import Certificado, Empresa, Manifestacao
from app.services.crypto import decrypt_bytes

logger = logging.getLogger(__name__)

_NS_NFE = "http://www.portalfiscal.inf.br/nfe"
_NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"

_DESC_EVENTO = {
    "210200": "Confirmacao da Operacao",
    "210210": "Ciencia da Operacao",
    "210220": "Desconhecimento da Operacao",
    "210240": "Operacao nao Realizada",
}

_XJUST_REQUIRED = {"210220", "210240"}


def _now_br() -> str:
    """Datetime no formato SEFAZ: 2026-06-16T14:30:00-03:00"""
    from datetime import timezone as tz
    import pytz
    sp = pytz.timezone("America/Sao_Paulo")
    return datetime.now(sp).strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":00"


def _build_inf_evento(
    chave: str,
    tipo_evento: str,
    cnpj: str,
    tp_amb: str,
    n_seq: int = 1,
    xjust: str = "",
) -> tuple:
    """Retorna (id_evento, xml_inf_evento_sem_assinatura)."""
    dh = _now_br()
    id_ev = f"ID{tipo_evento}{chave}{n_seq:02d}"
    desc = _DESC_EVENTO.get(tipo_evento, "Ciencia da Operacao")

    xjust_tag = f"<xJust>{xjust}</xJust>" if xjust else ""

    xml = (
        f'<infEvento xmlns="{_NS_NFE}" Id="{id_ev}" versao="1.00">'
        f"<cOrgao>91</cOrgao>"
        f"<tpAmb>{tp_amb}</tpAmb>"
        f"<CNPJ>{cnpj}</CNPJ>"
        f"<chNFe>{chave}</chNFe>"
        f"<dhEvento>{dh}</dhEvento>"
        f"<tpEvento>{tipo_evento}</tpEvento>"
        f"<nSeqEvento>{n_seq}</nSeqEvento>"
        f"<verEvento>1.00</verEvento>"
        f'<detEvento versao="1.00">'
        f"<descEvento>{desc}</descEvento>"
        f"{xjust_tag}"
        f"</detEvento>"
        f"</infEvento>"
    )
    return id_ev, xml


def _sign_xml(inf_evento_xml: str, cert_pem: bytes, key_pem: bytes) -> bytes:
    """Assina o infEvento com XML-DSig enveloped (RSA-SHA1 per NT SEFAZ)."""
    root = etree.fromstring(inf_evento_xml.encode())

    # Wrap em <evento> para a assinatura ficar embutida
    evento_el = etree.Element(f"{{{_NS_NFE}}}evento", versao="1.00")
    evento_el.append(root)

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )

    tf_cert = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    tf_key = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    try:
        tf_cert.write(cert_pem)
        tf_cert.flush()
        tf_key.write(key_pem)
        tf_key.flush()
        tf_cert.close()
        tf_key.close()
        signed = signer.sign(
            evento_el,
            key=tf_key.name,
            cert=tf_cert.name,
            reference_uri=f"#{root.get('Id')}",
        )
    finally:
        os.unlink(tf_cert.name)
        os.unlink(tf_key.name)

    return etree.tostring(signed, xml_declaration=True, encoding="UTF-8")


def _build_soap_envelope(evento_signed_xml: bytes, id_lote: int = 1) -> bytes:
    """Envolve o evento assinado no envelope SOAP da NFeRecepcaoEvento."""
    evento_el = etree.fromstring(evento_signed_xml)
    envelope = etree.Element(
        f"{{{_NS_SOAP}}}Envelope",
        nsmap={"soap": _NS_SOAP},
    )
    body = etree.SubElement(envelope, f"{{{_NS_SOAP}}}Body")
    recv = etree.SubElement(
        body,
        f"{{{_NS_NFE}}}nfeRecepcaoEvento",
        attrib={"versao": "1.00"},
    )
    recv.set("xmlns", _NS_NFE)
    lote = etree.SubElement(recv, f"{{{_NS_NFE}}}idLote")
    lote.text = str(id_lote)
    recv.append(evento_el)
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def _parse_recepcao_response(xml_bytes: bytes) -> dict:
    root = etree.fromstring(xml_bytes)
    ns = {"soap": _NS_SOAP, "nfe": _NS_NFE}
    ret = root.find(".//nfe:retEvento/nfe:infEvento", ns)
    if ret is None:
        ret = root.find(".//nfe:retEnvEvento", ns)
    if ret is None:
        return {"cstat": 0, "xmotivo": "resposta não reconhecida", "nprot": None}

    def txt(tag: str) -> Optional[str]:
        el = ret.find(f"nfe:{tag}", ns)
        return el.text.strip() if el is not None and el.text else None

    return {
        "cstat": int(txt("cStat") or "0"),
        "xmotivo": txt("xMotivo"),
        "nprot": txt("nProt"),
    }


def _pfx_to_pem(pfx_bytes: bytes, senha: str):
    private_key, cert, _ = pkcs12.load_key_and_certificates(
        pfx_bytes, senha.encode() if senha else b""
    )
    return (
        cert.public_bytes(Encoding.PEM),
        private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
    )


def _ssl_ctx(cert_pem: bytes, key_pem: bytes):
    import ssl
    ctx = ssl.create_default_context()
    tf_cert = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    tf_key = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    try:
        tf_cert.write(cert_pem)
        tf_cert.flush()
        tf_key.write(key_pem)
        tf_key.flush()
        tf_cert.close()
        tf_key.close()
        ctx.load_cert_chain(certfile=tf_cert.name, keyfile=tf_key.name)
    finally:
        os.unlink(tf_cert.name)
        os.unlink(tf_key.name)
    return ctx


def enfileirar(db, empresa_id: str, chave: str, tipo_evento: str = "210210", xjust: str = "") -> Manifestacao:
    """Cria registro de manifestação com status=pendente (idempotente por chave+tipo)."""
    existente = (
        db.query(Manifestacao)
        .filter_by(empresa_id=empresa_id, chave=chave, tipo_evento=tipo_evento)
        .filter(Manifestacao.status.in_(["pendente", "enviado"]))
        .first()
    )
    if existente:
        return existente

    mde = Manifestacao(
        empresa_id=empresa_id,
        chave=chave,
        tipo_evento=tipo_evento,
        status="pendente",
    )
    db.add(mde)
    db.commit()
    db.refresh(mde)
    return mde


def enviar_pendentes(db) -> int:
    """Processa todas as manifestações pendentes. Retorna quantidade enviada."""
    pendentes = (
        db.query(Manifestacao)
        .filter_by(status="pendente")
        .limit(50)
        .all()
    )
    enviados = 0
    for mde in pendentes:
        try:
            _enviar_um(db, mde)
            enviados += 1
        except Exception as exc:
            logger.error("Falha ao enviar manifestação %s (chave=%s): %s", mde.id, mde.chave, exc)
    return enviados


def _enviar_um(db, mde: Manifestacao) -> None:
    empresa = db.get(Empresa, mde.empresa_id)
    if not empresa:
        mde.status = "rejeitado"
        db.commit()
        return

    cert = (
        db.query(Certificado)
        .filter_by(empresa_id=mde.empresa_id, status="ativo")
        .order_by(Certificado.valido_ate.desc())
        .first()
    )
    if not cert:
        logger.warning("Empresa %s sem certificado ativo para manifestação", mde.empresa_id)
        return

    pfx_bytes = decrypt_bytes(cert.pfx_cifrado, settings.vault_master_key_bytes)
    senha = decrypt_bytes(cert.senha_cifrada, settings.vault_master_key_bytes).decode()
    cert_pem, key_pem = _pfx_to_pem(pfx_bytes, senha)

    id_ev, inf_xml = _build_inf_evento(
        chave=mde.chave,
        tipo_evento=mde.tipo_evento,
        cnpj=empresa.cnpj,
        tp_amb=settings.tp_amb,
    )

    try:
        signed_xml = _sign_xml(inf_xml, cert_pem, key_pem)
    except Exception as exc:
        logger.error("Falha na assinatura da manifestação %s: %s", mde.id, exc)
        mde.status = "rejeitado"
        db.commit()
        return

    soap = _build_soap_envelope(signed_xml)
    ssl_ctx = _ssl_ctx(cert_pem, key_pem)

    t0 = time.time()
    try:
        with httpx.Client(verify=ssl_ctx, timeout=30.0) as client:
            resp = client.post(
                settings.nfe_evento_endpoint,
                content=soap,
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            )
        resp.raise_for_status()
        ret = _parse_recepcao_response(resp.content)
    except Exception as exc:
        logger.error("Erro HTTP ao enviar manifestação %s: %s", mde.id, exc)
        return

    latencia_ms = int((time.time() - t0) * 1000)
    logger.info(
        "Manifestação %s chave=%s cStat=%s xMotivo=%s nprot=%s latencia=%dms",
        mde.tipo_evento, mde.chave, ret["cstat"], ret["xmotivo"], ret["nprot"], latencia_ms,
    )

    # cStat 135=processado com sucesso, 573=duplicidade (já enviado antes)
    if ret["cstat"] in (135, 573):
        mde.status = "enviado"
        mde.protocolo = ret["nprot"]
        mde.enviado_em = datetime.now(timezone.utc)
    else:
        mde.status = "rejeitado"

    db.commit()
