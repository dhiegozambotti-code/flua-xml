"""
Proxy mTLS para os webservices do eSocial do governo federal.
Usa dnspython para resolver gov.br via 8.8.8.8 (Railway não resolve .gov.br por padrão).
"""
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request
from typing import Literal

import dns.resolver as _dns

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/esocial", tags=["esocial"])

HOST = {
    1: "webservices.esocial.gov.br",
    2: "webservices.producaorestrita.esocial.gov.br",
}

NS_ENVIO = "http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/v1_1_1"
NS_CONSULTA = "http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/consulta/retornoProcessamento/v1_0_0"
NS_CONSULTA_SCHEMA = "http://www.esocial.gov.br/schema/lote/eventos/envio/consulta/retornoProcessamento/v1_0_0"


def _soap_envelope(ns: str, action: str, to: str, body: str) -> str:
    # SOAP 1.1 envelope + WS-Addressing headers (basicHttpBinding + WSAddressing no WCF do eSocial)
    return (
        f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
        f' xmlns:a="http://www.w3.org/2005/08/addressing" xmlns:v1="{ns}">'
        f'<soapenv:Header>'
        f'<a:Action soapenv:mustUnderstand="1">{action}</a:Action>'
        f'<a:To soapenv:mustUnderstand="1">{to}</a:To>'
        f'</soapenv:Header>'
        f"<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>"
    )


def _pick(xml: str, tag: str) -> str | None:
    m = re.search(rf"<(?:\w+:)?{tag}[^>]*>([\s\S]*?)</(?:\w+:)?{tag}>", xml, re.IGNORECASE)
    return m.group(1).strip() if m else None


# webservices.esocial.gov.br não tem registro público DNS (split-horizon SERPRO).
# IP confirmado via resolução local no Brasil: 200.198.235.238 (mesmo servidor, Host header diferencia).
_ESOCIAL_IP = "200.198.235.238"


def _resolve_ip(hostname: str) -> str:
    return _ESOCIAL_IP


def _soap_post(host: str, path: str, action: str, envelope: str, cert_pem: str, key_pem: str) -> str:
    with (
        tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as cf,
        tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as kf,
    ):
        cf.write(cert_pem)
        kf.write(key_pem)
        cert_path, key_path = cf.name, kf.name

    try:
        ip = _resolve_ip(host)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        ctx.load_default_certs()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        body_bytes = envelope.encode("utf-8")
        req = urllib.request.Request(
            f"https://{ip}{path}",
            data=body_bytes,
            method="POST",
            headers={
                "Content-Type": "text/xml;charset=UTF-8",
                "SOAPAction": f'"{action}"',
                "Content-Length": str(len(body_bytes)),
                "Host": host,
            },
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            print(f"[esocial] HTTP {e.code} {e.reason} | body={body[:300]!r}")
            return body or f"<ProxyError><status>{e.code}</status><reason>{e.reason}</reason></ProxyError>"
    finally:
        os.unlink(cert_path)
        os.unlink(key_path)


def _check_auth(authorization: str | None) -> None:
    secret = os.getenv("ESOCIAL_PROXY_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="ESOCIAL_PROXY_SECRET não configurado")
    if authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


class EnviarInput(BaseModel):
    lote_xml: str
    cert_pem: str
    key_pem: str
    ambiente: Literal[1, 2]


class ConsultarInput(BaseModel):
    protocolo: str
    cert_pem: str
    key_pem: str
    ambiente: Literal[1, 2]


@router.post("/enviar")
def enviar(body: EnviarInput, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    host = HOST[body.ambiente]
    path = "/servicos/empregador/enviarloteeventos/WsEnviarLoteEventos.svc"
    action = f"{NS_ENVIO}/IServicoEnviarLoteEventos/EnviarLoteEventos"
    to = f"https://{host}{path}"
    soap_body = f"<v1:EnviarLoteEventos><v1:loteEventos>{body.lote_xml}</v1:loteEventos></v1:EnviarLoteEventos>"
    envelope = _soap_envelope(NS_ENVIO, action, to, soap_body)
    try:
        bruto = _soap_post(host, path, action, envelope, body.cert_pem, body.key_pem)
        descricao = _pick(bruto, "descResposta") or _pick(bruto, "faultstring") or _pick(bruto, "Text")
        return {
            "bruto": bruto,
            "protocolo": _pick(bruto, "protocoloEnvio") or _pick(bruto, "protocolo"),
            "codigo": _pick(bruto, "cdResposta"),
            "descricao": descricao,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/consultar")
def consultar(body: ConsultarInput, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    host = HOST[body.ambiente]
    path = "/servicos/empregador/consultarloteeventos/WsConsultarLoteEventos.svc"
    action = f"{NS_CONSULTA}/IServicoConsultarLoteEventos/ConsultarLoteEventos"
    to = f"https://{host}{path}"
    consulta = (
        f'<eSocial xmlns="{NS_CONSULTA_SCHEMA}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<consultaLoteEventos><protocoloEnvio>{body.protocolo}</protocoloEnvio></consultaLoteEventos></eSocial>"
    )
    soap_body = f"<v1:ConsultarLoteEventos><v1:consulta>{consulta}</v1:consulta></v1:ConsultarLoteEventos>"
    envelope = _soap_envelope(NS_CONSULTA, action, to, soap_body)
    try:
        bruto = _soap_post(host, path, action, envelope, body.cert_pem, body.key_pem)
        return {
            "bruto": bruto,
            "codigo": _pick(bruto, "cdResposta"),
            "descricao": _pick(bruto, "descResposta"),
            "recibo": _pick(bruto, "nrRecibo"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
