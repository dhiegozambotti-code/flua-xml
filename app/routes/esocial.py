"""
Proxy mTLS para os webservices do eSocial do governo federal.
O Railway não resolve .gov.br via getaddrinfo, então batemos direto no IP com header Host.
Produção real usa hosts separados para envio e consulta (webservices.envio / webservices.consulta);
o antigo webservices.esocial.gov.br foi desativado. Restrita usa um único host para ambos.
"""
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/esocial", tags=["esocial"])

# (ambiente, serviço) -> (host, ip). IPs sobrescrevíveis por env (sobrevivem a troca de IP sem deploy).
ENDPOINTS = {
    (1, "enviar"): (
        "webservices.envio.esocial.gov.br",
        os.getenv("ESOCIAL_ENVIO_PROD_IP", "189.9.104.164"),
    ),
    (1, "consultar"): (
        "webservices.consulta.esocial.gov.br",
        os.getenv("ESOCIAL_CONSULTA_PROD_IP", "189.9.104.163"),
    ),
    (1, "download"): (
        "webservices.download.esocial.gov.br",
        os.getenv("ESOCIAL_DOWNLOAD_PROD_IP", "189.9.104.199"),
    ),
    (2, "enviar"): (
        "webservices.producaorestrita.esocial.gov.br",
        os.getenv("ESOCIAL_RESTRITA_IP", "200.198.235.238"),
    ),
    (2, "consultar"): (
        "webservices.producaorestrita.esocial.gov.br",
        os.getenv("ESOCIAL_RESTRITA_IP", "200.198.235.238"),
    ),
    (2, "download"): (
        "webservices.producaorestrita.esocial.gov.br",
        os.getenv("ESOCIAL_RESTRITA_IP", "200.198.235.238"),
    ),
}


def _endpoint(ambiente: int, servico: str) -> tuple[str, str]:
    return ENDPOINTS[(ambiente, servico)]

NS_ENVIO = "http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/v1_1_0"
NS_CONSULTA = "http://www.esocial.gov.br/servicos/empregador/lote/eventos/envio/consulta/retornoProcessamento/v1_1_0"
NS_CONSULTA_SCHEMA = "http://www.esocial.gov.br/schema/lote/eventos/envio/consulta/retornoProcessamento/v1_0_0"


def _soap_envelope(ns: str, action: str, to: str, body: str) -> str:
    # SOAP 1.1 puro (basicHttpBinding do eSocial — despacho via header SOAPAction,
    # sem WS-Addressing no runtime apesar do wsaw:Action no WSDL).
    return (
        f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v1="{ns}">'
        f"<soapenv:Header/><soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>"
    )


def _pick(xml: str, tag: str) -> str | None:
    m = re.search(rf"<(?:\w+:)?{tag}[^>]*>([\s\S]*?)</(?:\w+:)?{tag}>", xml, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _soap_post(host: str, ip: str, path: str, action: str, envelope: str, cert_pem: str, key_pem: str) -> str:
    with (
        tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as cf,
        tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as kf,
    ):
        cf.write(cert_pem)
        kf.write(key_pem)
        cert_path, key_path = cf.name, kf.name

    try:
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
            with urllib.request.urlopen(req, context=ctx, timeout=45) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            # SOAP Fault do eSocial vem como HTTP 500 — lemos o body para extrair o erro.
            body = e.read().decode("utf-8")
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
    host, ip = _endpoint(body.ambiente, "enviar")
    path = "/servicos/empregador/enviarloteeventos/WsEnviarLoteEventos.svc"
    action = f"{NS_ENVIO}/ServicoEnviarLoteEventos/EnviarLoteEventos"
    to = f"https://{host}{path}"
    soap_body = f"<v1:EnviarLoteEventos><v1:loteEventos>{body.lote_xml}</v1:loteEventos></v1:EnviarLoteEventos>"
    envelope = _soap_envelope(NS_ENVIO, action, to, soap_body)
    try:
        bruto = _soap_post(host, ip, path, action, envelope, body.cert_pem, body.key_pem)
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
    host, ip = _endpoint(body.ambiente, "consultar")
    path = "/servicos/empregador/consultarloteeventos/WsConsultarLoteEventos.svc"
    action = f"{NS_CONSULTA}/ServicoConsultarLoteEventos/ConsultarLoteEventos"
    to = f"https://{host}{path}"
    consulta = (
        f'<eSocial xmlns="{NS_CONSULTA_SCHEMA}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<consultaLoteEventos><protocoloEnvio>{body.protocolo}</protocoloEnvio></consultaLoteEventos></eSocial>"
    )
    soap_body = f"<v1:ConsultarLoteEventos><v1:consulta>{consulta}</v1:consulta></v1:ConsultarLoteEventos>"
    envelope = _soap_envelope(NS_CONSULTA, action, to, soap_body)
    try:
        bruto = _soap_post(host, ip, path, action, envelope, body.cert_pem, body.key_pem)
        return {
            "bruto": bruto,
            "codigo": _pick(bruto, "cdResposta"),
            "descricao": _pick(bruto, "descResposta"),
            "recibo": _pick(bruto, "nrRecibo"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Consulta/Download de eventos por trabalhador (eSocial BX, host de consulta) ──
# Usado para puxar S-2200/S-2300 já transmitidos e auto-preencher o cadastro.
# ⚠️ Estrutura best-effort (sped-esocial) — validar action/wrapper ao vivo, como nas tabelas.
NS_IDENT = "http://www.esocial.gov.br/servicos/empregador/consulta/identificadores-eventos/v1_0_0"
NS_IDENT_SCHEMA = "http://www.esocial.gov.br/schema/consulta/identificadores-eventos/trabalhador/v1_0_0"
NS_DOWNLOAD = "http://www.esocial.gov.br/servicos/empregador/download/solicitacao/v1_0_0"
NS_DOWNLOAD_SCHEMA = "http://www.esocial.gov.br/schema/download/solicitacao/id/v1_0_0"


class IdentInput(BaseModel):
    cnpj: str
    cpf: str
    dt_ini: str  # AAAA-MM-DD
    dt_fim: str
    cert_pem: str
    key_pem: str
    ambiente: Literal[1, 2]


class DownloadInput(BaseModel):
    cnpj: str
    ids: list[str]
    cert_pem: str
    key_pem: str
    ambiente: Literal[1, 2]


@router.post("/consultar-identificadores")
def consultar_identificadores(body: IdentInput, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    host, ip = _endpoint(body.ambiente, "download")
    path = "/servicos/empregador/dwlcirurgico/WsConsultarIdentificadoresEventos.svc"
    action = f"{NS_IDENT}/ServicoConsultarIdentificadoresEventos/ConsultarIdentificadoresEventosTrabalhador"
    to = f"https://{host}{path}"
    base8 = body.cnpj.replace(" ", "")[:8]
    cpf = body.cpf.replace(".", "").replace("-", "")
    inner = (
        f'<eSocial xmlns="{NS_IDENT_SCHEMA}">'
        f"<consultaIdentificadoresEvts><ideEmpregador><tpInsc>1</tpInsc><nrInsc>{base8}</nrInsc></ideEmpregador>"
        f"<consultaEvtsTrabalhador><cpfTrab>{cpf}</cpfTrab><dtIni>{body.dt_ini}</dtIni><dtFim>{body.dt_fim}</dtFim></consultaEvtsTrabalhador>"
        f"</consultaIdentificadoresEvts></eSocial>"
    )
    soap_body = (
        f"<v1:ConsultarIdentificadoresEventosTrabalhador>"
        f"<v1:consultaEventosTrabalhador>{inner}</v1:consultaEventosTrabalhador>"
        f"</v1:ConsultarIdentificadoresEventosTrabalhador>"
    )
    envelope = _soap_envelope(NS_IDENT, action, to, soap_body)
    try:
        bruto = _soap_post(host, ip, path, action, envelope, body.cert_pem, body.key_pem)
        ids = re.findall(r"<(?:\w+:)?id>([^<]+)</(?:\w+:)?id>", bruto)
        recibos = re.findall(r"<(?:\w+:)?nrRec[^>]*>([^<]+)</", bruto)
        return {"bruto": bruto, "ids": ids, "recibos": recibos, "descricao": _pick(bruto, "cdResposta")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/download-eventos")
def download_eventos(body: DownloadInput, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    host, ip = _endpoint(body.ambiente, "download")
    path = "/servicos/empregador/dwlcirurgico/WsSolicitarDownloadEventos.svc"
    action = f"{NS_DOWNLOAD}/ServicoSolicitarDownloadEventos/SolicitarDownloadEventosPorId"
    to = f"https://{host}{path}"
    base8 = body.cnpj.replace(" ", "")[:8]
    ids_xml = "".join(f"<id>{i}</id>" for i in body.ids)
    inner = (
        f'<eSocial xmlns="{NS_DOWNLOAD_SCHEMA}">'
        f"<download><ideEmpregador><tpInsc>1</tpInsc><nrInsc>{base8}</nrInsc></ideEmpregador>"
        f"<solicDownloadEvtsPorId>{ids_xml}</solicDownloadEvtsPorId></download></eSocial>"
    )
    soap_body = (
        f"<v1:SolicitarDownloadEventosPorId>"
        f"<v1:solicitacao>{inner}</v1:solicitacao>"
        f"</v1:SolicitarDownloadEventosPorId>"
    )
    envelope = _soap_envelope(NS_DOWNLOAD, action, to, soap_body)
    try:
        bruto = _soap_post(host, ip, path, action, envelope, body.cert_pem, body.key_pem)
        return {"bruto": bruto}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
