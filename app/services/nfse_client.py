"""Cliente REST para a Distribuição de DF-e do ADN NFS-e (Padrão Nacional).

Portal Nacional NFS-e (gov.br/nfse) — API de Distribuição dos Contribuintes.
Autenticação mTLS com certificado A1 (.pfx), igual à NF-e, mas o transporte é
REST/JSON em vez de SOAP. Documentos vêm em XML GZip+Base64 (mesma codificação
do docZip da NF-e).

A interface (`dist_nsu`) imita a do NFeSoapClient para ser drop-in no
orquestrador: retorna o mesmo dict {cstat, xmotivo, ult_nsu, max_nsu, docs}.

Métodos da API:
  GET /DFe/{NSU}                  -> lote de até 50 DF-e a partir do NSU
  GET /NFSe/{ChaveAcesso}/Eventos -> eventos por chave (FASE 2)
"""

import logging
from typing import Any, Dict, List

import httpx

# Reuso direto: conversão pfx->pem e montagem do SSLContext mTLS.
# Importar este módulo também ativa o monkey-patch de DNS (.gov.br) do SEFAZ.
from app.services.sefaz_client import _build_ssl_context, _pfx_to_pem

logger = logging.getLogger(__name__)


def _first(d: Dict[str, Any], *keys, default=None):
    """Retorna o primeiro valor presente entre variações de nome de chave."""
    if not isinstance(d, dict):
        return default
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower and lower[k.lower()] is not None:
            return lower[k.lower()]
    return default


def _extrair_docs(payload: Any) -> List[Dict[str, Any]]:
    """Extrai a lista de documentos do JSON de resposta, tolerante a variações.

    Cada item vira {"nsu": int, "schema": "nfse"|"eventonfse", "b64": str}.
    O conteúdo (XML GZip+Base64) é detectado por nomes comuns de campo.
    """
    if payload is None:
        return []
    # A lista pode estar na raiz ou sob uma chave de lote
    lista = None
    if isinstance(payload, list):
        lista = payload
    elif isinstance(payload, dict):
        lista = _first(payload, "LoteDFe", "loteDFe", "lote", "DFe", "Documentos",
                       "DocumentosFiscais", "documentos", default=None)
        if lista is None:
            # talvez o próprio payload seja um único documento
            if _first(payload, "ArquivoXml", "arquivoXml", "xmlGZipB64", "documentoXml"):
                lista = [payload]
            else:
                lista = []
    docs: List[Dict[str, Any]] = []
    for item in lista or []:
        b64 = _first(item, "ArquivoXml", "arquivoXml", "xmlGZipB64", "documentoXml",
                     "conteudo", "xml")
        if not b64:
            continue
        nsu = _first(item, "NSU", "nsu", default=0)
        try:
            nsu = int(nsu)
        except (TypeError, ValueError):
            nsu = 0
        tipo = (_first(item, "TipoDocumento", "tipoDocumento", "tipo", default="") or "")
        schema = "eventonfse" if "evento" in str(tipo).lower() else "nfse"
        docs.append({"nsu": nsu, "schema": schema, "b64": b64})
    return docs


class NfseRestClient:
    """Cliente REST mTLS para a Distribuição DFe do ADN NFS-e."""

    def __init__(self, pfx_bytes: bytes, senha: str, endpoint: str,
                 tp_amb: str = "2", timeout: float = 30.0):
        self.endpoint = endpoint.rstrip("/")
        self.tp_amb = tp_amb
        self.timeout = timeout
        cert_pem, key_pem = _pfx_to_pem(pfx_bytes, senha)
        self._ssl_ctx = _build_ssl_context(cert_pem, key_pem)

    def dist_nsu(self, uf: str, cnpj: str, ult_nsu: int) -> Dict[str, Any]:
        """Busca o lote de DF-e a partir do NSU informado (GET /DFe/{NSU}).

        `uf` é ignorado (mantido para ser drop-in com o NFeSoapClient).
        Mapeia a resposta HTTP para o contrato do orquestrador:
          - 200 com docs   -> cstat 138
          - 200/204 sem doc -> cstat 137
          - 4xx/5xx         -> raise (loop trata com retry/backoff)
        """
        url = f"{self.endpoint}/DFe/{int(ult_nsu)}"
        with httpx.Client(verify=self._ssl_ctx, timeout=self.timeout) as client:
            resp = client.get(url, headers={"Accept": "application/json"})

        if resp.status_code == 204:
            return {"cstat": 137, "xmotivo": "Nenhum documento localizado",
                    "ult_nsu": ult_nsu, "max_nsu": ult_nsu, "docs": []}
        if resp.status_code >= 400:
            logger.error("ADN NFS-e HTTP %s — body: %s", resp.status_code, resp.text[:1500])
            raise RuntimeError(f"ADN NFS-e HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Resposta ADN não-JSON: {exc}; body={resp.text[:300]}")

        # Primeiro contato: logar JSON cru para confirmar nomes de campo.
        logger.info("ADN NFS-e /DFe/%s -> keys=%s",
                    ult_nsu, list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)

        docs = _extrair_docs(payload)
        novo_ult = _first(payload, "ultimoNSU", "ultNSU", "ultimoNsu", default=None) if isinstance(payload, dict) else None
        max_nsu = _first(payload, "maxNSU", "maximoNSU", "maxNsu", default=None) if isinstance(payload, dict) else None

        try:
            novo_ult = int(novo_ult) if novo_ult is not None else (max(d["nsu"] for d in docs) if docs else ult_nsu)
        except (TypeError, ValueError):
            novo_ult = ult_nsu
        try:
            max_nsu = int(max_nsu) if max_nsu is not None else novo_ult
        except (TypeError, ValueError):
            max_nsu = novo_ult

        if not docs:
            return {"cstat": 137, "xmotivo": "Nenhum documento localizado",
                    "ult_nsu": novo_ult, "max_nsu": max_nsu, "docs": []}

        return {"cstat": 138, "xmotivo": "Documento(s) localizado(s)",
                "ult_nsu": novo_ult, "max_nsu": max_nsu, "docs": docs}

    def consultar_eventos(self, chave: str) -> Dict[str, Any]:
        """GET /NFSe/{ChaveAcesso}/Eventos — eventos por chave (FASE 2)."""
        url = f"{self.endpoint}/NFSe/{chave}/Eventos"
        with httpx.Client(verify=self._ssl_ctx, timeout=self.timeout) as client:
            resp = client.get(url, headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            raise RuntimeError(f"ADN NFS-e eventos HTTP {resp.status_code}")
        return {"docs": _extrair_docs(resp.json())}
