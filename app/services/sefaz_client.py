"""Cliente SOAP para NFeDistribuicaoDFe (NT 2014.002).

Usa httpx + mTLS com certificado A1 (.pfx) descriptografado em memória.
Nunca escreve chave privada em disco.
"""

import logging
import os
import socket
import ssl
import tempfile
import time
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from lxml import etree

logger = logging.getLogger(__name__)

# Mapeamento hostname → IP para contornar DNS de provedores que não resolvem .gov.br
# Configurável via env var: SEFAZ_HOSTS_OVERRIDE="host1:ip1,host2:ip2"
_HOSTS_OVERRIDE: Dict[str, str] = {
    "www1.nfe.fazenda.gov.br": "200.198.239.181",
    "cte.fazenda.gov.br": "200.198.239.181",
    "mdfe.fazenda.gov.br": "200.198.239.181",
    "www.nfe.fazenda.gov.br": "200.198.239.181",
    "nfe.svrs.rs.gov.br": "4.201.99.36",
    "homologacao.nfe.fazenda.gov.br": "200.198.239.133",
    "hom1.nfe.fazenda.gov.br": "200.198.239.133",
}

# Injetar overrides extras via env var
for _entry in os.environ.get("SEFAZ_HOSTS_OVERRIDE", "").split(","):
    if ":" in _entry:
        _h, _ip = _entry.strip().split(":", 1)
        _HOSTS_OVERRIDE[_h.strip()] = _ip.strip()

# Monkey-patch socket.getaddrinfo E socket.create_connection para cobrir
# todos os caminhos de resolução usados por httpx/httpcore no Railway.
_orig_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, *args, **kwargs):
    if isinstance(host, str) and host in _HOSTS_OVERRIDE:
        logger.debug("DNS override (getaddrinfo) %s → %s", host, _HOSTS_OVERRIDE[host])
        host = _HOSTS_OVERRIDE[host]
    return _orig_getaddrinfo(host, port, *args, **kwargs)

socket.getaddrinfo = _patched_getaddrinfo

_orig_create_connection = socket.create_connection

def _patched_create_connection(address, *args, **kwargs):
    host, port = address
    if isinstance(host, str) and host in _HOSTS_OVERRIDE:
        logger.debug("DNS override (create_connection) %s → %s", host, _HOSTS_OVERRIDE[host])
        host = _HOSTS_OVERRIDE[host]
    return _orig_create_connection((host, port), *args, **kwargs)

socket.create_connection = _patched_create_connection

_NS_NFE  = "http://www.portalfiscal.inf.br/nfe"
_NS_MDFE = "http://www.portalfiscal.inf.br/mdfe"
_NS_CTE = "http://www.portalfiscal.inf.br/cte"
_NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"

# Tags raiz de cada serviço de distribuição
_DIST_ROOT = {
    "nfe": ("nfeDistDFeInteresse", _NS_NFE),
    "nfce": ("nfeDistDFeInteresse", _NS_NFE),
    "cte":  ("cteDistDFeInteresse",  _NS_CTE),
    "mdfe": ("mdfeDistDFeInteresse", _NS_MDFE),
}

# UF → código IBGE (cUFAutor)
_UF_CODES: Dict[str, int] = {
    "AC": 12, "AL": 27, "AP": 16, "AM": 13, "BA": 29, "CE": 23, "DF": 53,
    "ES": 32, "GO": 52, "MA": 21, "MT": 51, "MS": 50, "MG": 31, "PA": 15,
    "PB": 25, "PR": 41, "PE": 26, "PI": 22, "RJ": 33, "RN": 24, "RS": 43,
    "RO": 11, "RR": 14, "SC": 42, "SP": 35, "SE": 28, "TO": 17,
}


def uf_to_code(uf: str) -> int:
    code = _UF_CODES.get((uf or "").upper())
    if not code:
        raise ValueError(f"UF inválida: {uf}")
    return code


def _pfx_to_pem(pfx_bytes: bytes, senha: str) -> tuple:
    """Converte .pfx → (cert_pem, key_pem) em memória."""
    private_key, cert, _ = pkcs12.load_key_and_certificates(
        pfx_bytes, senha.encode() if senha else b""
    )
    cert_pem = cert.public_bytes(Encoding.PEM)
    key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    return cert_pem, key_pem


def _build_ssl_context(cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    """Cria SSLContext com o certificado cliente; usa tmp files que são deletados logo."""
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


_WSDL_NS = {
    "nfe":  "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe",
    "nfce": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe",
    "cte":  "http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe",
    "mdfe": "http://www.portalfiscal.inf.br/mdfe/wsdl/MdFeDistribuicaoDFe",
}

_DIST_TAG = {
    "nfe":  "distDFeInt",
    "nfce": "distDFeInt",
    "cte":  "distDFeInt",
    "mdfe": "distDFeInt",
}

def _soap_envelope(tp_amb: str, uf_code: int, cnpj: str, inner_xml: str,
                   modelo: str = "nfe") -> str:
    _, doc_ns = _DIST_ROOT.get(modelo, _DIST_ROOT["nfe"])
    wsdl_ns = _WSDL_NS.get(modelo, _WSDL_NS["nfe"])
    dist_tag = _DIST_TAG.get(modelo, "distDFeInt")
    cab_tag = "nfeCabecMsg" if modelo in ("nfe", "nfce") else "cteCabecMsg" if modelo == "cte" else "mdfeCabecMsg"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
        "<soap:Header>"
        f'<{cab_tag} xmlns="{wsdl_ns}">'
        f"<cUF>{uf_code}</cUF>"
        "<versaoDados>1.01</versaoDados>"
        f"</{cab_tag}>"
        "</soap:Header>"
        "<soap:Body>"
        f'<nfeDadosMsg xmlns="{wsdl_ns}">'
        f'<{dist_tag} xmlns="{doc_ns}" versao="1.01">'
        f"<tpAmb>{tp_amb}</tpAmb>"
        f"<cUFAutor>{uf_code}</cUFAutor>"
        f"<CNPJ>{cnpj}</CNPJ>"
        f"{inner_xml}"
        f"</{dist_tag}>"
        "</nfeDadosMsg>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


def _parse_response(xml_bytes: bytes, modelo: str = "nfe") -> Dict[str, Any]:
    root = etree.fromstring(xml_bytes)

    # CT-e usa namespace próprio; NF-e usa _NS_NFE
    doc_ns = _NS_CTE if modelo == "cte" else (_NS_MDFE if modelo == "mdfe" else _NS_NFE)
    ns = {"soap": _NS_SOAP, "doc": doc_ns}

    ret = root.find(".//doc:retDistDFeInt", ns)
    if ret is None:
        # fallback — alguns SEFAZ respondem sem namespace correto
        ret = root.find(".//{%s}retDistDFeInt" % doc_ns)
    if ret is None:
        raise ValueError(f"Resposta SEFAZ sem retDistDFeInt (modelo={modelo})")

    def txt(tag: str) -> str:
        el = ret.find(f"doc:{tag}", ns)
        if el is None:
            el = ret.find("{%s}%s" % (doc_ns, tag))
        return el.text.strip() if el is not None and el.text else ""

    cstat = int(txt("cStat") or "0")
    docs: List[Dict[str, Any]] = []
    for dz in ret.findall(".//doc:docZip", ns):
        docs.append({
            "schema": dz.get("schema", ""),
            "nsu": int(dz.get("NSU") or dz.get("nsu") or "0"),
            "b64": (dz.text or "").strip(),
        })

    return {
        "cstat": cstat,
        "xmotivo": txt("xMotivo"),
        "ult_nsu": int(txt("ultNSU") or "0"),
        "max_nsu": int(txt("maxNSU") or "0"),
        "docs": docs,
    }


class NFeSoapClient:
    """Cliente SOAP genérico para NFeDistribuicaoDFe e CTeDistribuicaoDFe."""

    def __init__(
        self,
        pfx_bytes: bytes,
        senha: str,
        endpoint: str,
        tp_amb: str = "2",
        modelo: str = "nfe",   # nfe | nfce | cte
        timeout: float = 30.0,
    ):
        self.endpoint = endpoint
        self.tp_amb = tp_amb
        self.modelo = modelo
        self.timeout = timeout
        cert_pem, key_pem = _pfx_to_pem(pfx_bytes, senha)
        self._ssl_ctx = _build_ssl_context(cert_pem, key_pem)

    def _post(self, body: str) -> Dict[str, Any]:
        wsdl_ns = _WSDL_NS.get(self.modelo, _WSDL_NS["nfe"])
        action = f"{wsdl_ns}/nfeDistDFeInteresse"
        # SOAP 1.2: action vai no Content-Type, não como header separado
        content_type = f'application/soap+xml; charset=utf-8; action="{action}"'
        with httpx.Client(verify=self._ssl_ctx, timeout=self.timeout) as client:
            resp = client.post(
                self.endpoint,
                content=body.encode("utf-8"),
                headers={"Content-Type": content_type},
            )
        resp.raise_for_status()
        return _parse_response(resp.content, self.modelo)

    def dist_nsu(self, uf: str, cnpj: str, ult_nsu: int) -> Dict[str, Any]:
        uf_code = uf_to_code(uf)
        inner = f"<distNSU><ultNSU>{ult_nsu:015d}</ultNSU></distNSU>"
        body = _soap_envelope(self.tp_amb, uf_code, cnpj, inner, self.modelo)
        logger.debug("distNSU modelo=%s cnpj=%s ult_nsu=%s", self.modelo, cnpj, ult_nsu)
        return self._post(body)

    def cons_nsu(self, uf: str, cnpj: str, nsu: int) -> Dict[str, Any]:
        uf_code = uf_to_code(uf)
        inner = f"<consNSU><NSU>{nsu:015d}</NSU></consNSU>"
        body = _soap_envelope(self.tp_amb, uf_code, cnpj, inner, self.modelo)
        return self._post(body)

    def cons_ch_nfe(self, uf: str, cnpj: str, chave: str) -> Dict[str, Any]:
        """Consulta por chave — disponível apenas para NF-e."""
        uf_code = uf_to_code(uf)
        inner = f"<consChNFe><chNFe>{chave}</chNFe></consChNFe>"
        body = _soap_envelope(self.tp_amb, uf_code, cnpj, inner)
        return self._post(body)
