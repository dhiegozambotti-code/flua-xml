"""Parser de docZip: Base64 → Gzip → XML → metadados.

Suporta: procNFe, resNFe, procEventoNFe, resEventoNFe.
Inclui extração dos campos IBSCBS (Reforma Tributária 2026+).
"""

import base64
import gzip
import hashlib
import logging
from typing import Any, Dict, Optional

from lxml import etree

logger = logging.getLogger(__name__)

_NS = {
    "nfe": "http://www.portalfiscal.inf.br/nfe",
    "cte": "http://www.portalfiscal.inf.br/cte",
}


def decompress_doczip(b64_content: str) -> bytes:
    compressed = base64.b64decode(b64_content)
    return gzip.decompress(compressed)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _txt(el: Any, xpath: str, ns: dict = _NS) -> Optional[str]:
    found = el.find(xpath, ns)
    return found.text.strip() if found is not None and found.text else None


def _parse_proc_nfe(root: Any) -> Dict[str, Any]:
    nfe = root.find(".//nfe:NFe", _NS)
    inf = nfe.find("nfe:infNFe", _NS) if nfe is not None else None
    if inf is None:
        return {}

    emit = inf.find("nfe:emit", _NS)
    dest = inf.find("nfe:dest", _NS)
    ide = inf.find("nfe:ide", _NS)
    total = inf.find("nfe:total/nfe:ICMSTot", _NS)

    emit_cnpj = _txt(emit, "nfe:CNPJ") if emit is not None else None
    dest_cnpj = _txt(dest, "nfe:CNPJ") if dest is not None else None
    dest_cpf = _txt(dest, "nfe:CPF") if dest is not None else None

    # IBSCBS — Reforma Tributária (NT 2026.001)
    ibscbs = inf.find(".//nfe:IBSCBS", _NS)
    ibscbs_data = None
    if ibscbs is not None:
        ibscbs_data = {
            "cst": _txt(ibscbs, "nfe:CST"),
            "cclass_trib": _txt(ibscbs, "nfe:cClassTrib"),
            "nbs": _txt(ibscbs, "nfe:NBS"),
        }

    prot = root.find(".//nfe:protNFe/nfe:infProt", _NS)

    # Detecta NFC-e (modelo 65) vs NF-e (modelo 55)
    mod = _txt(ide, "nfe:mod") if ide is not None else None
    modelo_doc = "nfce" if mod == "65" else "nfe"

    return {
        "chave": inf.get("Id", "").replace("NFe", ""),
        "emit_cnpj": emit_cnpj,
        "dest_cnpj": dest_cnpj or dest_cpf,
        "valor_total": _txt(total, "nfe:vNF") if total is not None else None,
        "dh_emissao": _txt(ide, "nfe:dhEmi") if ide is not None else None,
        "situacao": "autorizada" if prot is not None else "desconhecida",
        "ibscbs": ibscbs_data,
        "modelo_doc": modelo_doc,  # nfe | nfce
    }


def _parse_res_nfe(root: Any) -> Dict[str, Any]:
    res = root.find(".//nfe:resNFe", _NS) or root
    return {
        "chave": _txt(res, "nfe:chNFe"),
        "emit_cnpj": _txt(res, "nfe:CNPJ"),
        "dest_cnpj": None,
        "valor_total": _txt(res, "nfe:vNF"),
        "dh_emissao": _txt(res, "nfe:dhEmi"),
        "situacao": _txt(res, "nfe:digVal") and "autorizada" or "desconhecida",
    }


def _parse_evento(root: Any) -> Dict[str, Any]:
    det = root.find(".//nfe:detEvento", _NS)
    inf_ev = root.find(".//nfe:infEvento", _NS)
    if inf_ev is None:
        inf_ev = root.find(".//nfe:evento/nfe:infEvento", _NS)
    return {
        "chave": _txt(inf_ev, "nfe:chNFe") if inf_ev is not None else None,
        "emit_cnpj": _txt(inf_ev, "nfe:CNPJ") if inf_ev is not None else None,
        "dest_cnpj": None,
        "valor_total": None,
        "dh_emissao": _txt(inf_ev, "nfe:dhEvento") if inf_ev is not None else None,
        "situacao": "evento",
        "tipo_evento": _txt(inf_ev, "nfe:tpEvento") if inf_ev is not None else None,
    }


_NS_CTE = {"cte": "http://www.portalfiscal.inf.br/cte"}


def _parse_proc_cte(root: Any) -> Dict[str, Any]:
    """Extrai metadados de procCTe (CT-e completo autorizado)."""
    cte = root.find(".//cte:CTe", _NS_CTE)
    inf = cte.find("cte:infCte", _NS_CTE) if cte is not None else None
    if inf is None:
        return {}

    ide = inf.find("cte:ide", _NS_CTE)
    emit = inf.find("cte:emit", _NS_CTE)
    dest = inf.find("cte:dest", _NS_CTE)
    rem = inf.find("cte:rem", _NS_CTE)
    receb = inf.find("cte:receb", _NS_CTE)
    vPrest = inf.find("cte:vPrest", _NS_CTE)

    # Tomador: 0=rem, 1=exped, 2=receb, 3=dest
    toma = ide.find("cte:toma3", _NS_CTE) if ide is not None else None
    if toma is None and ide is not None:
        toma = ide.find("cte:toma4", _NS_CTE)
    tomador = _txt(toma, "cte:toma", _NS_CTE) if toma is not None else None

    prot = root.find(".//cte:protCTe/cte:infProt", _NS_CTE)

    return {
        "chave": inf.get("Id", "").replace("CTe", ""),
        "emit_cnpj": _txt(emit, "cte:CNPJ", _NS_CTE) if emit is not None else None,
        "dest_cnpj": _txt(dest, "cte:CNPJ", _NS_CTE) if dest is not None else None,
        "rem_cnpj": _txt(rem, "cte:CNPJ", _NS_CTE) if rem is not None else None,
        "rec_cnpj": _txt(receb, "cte:CNPJ", _NS_CTE) if receb is not None else None,
        "valor_total": _txt(vPrest, "cte:vTPrest", _NS_CTE) if vPrest is not None else None,
        "dh_emissao": _txt(ide, "cte:dhEmi", _NS_CTE) if ide is not None else None,
        "modal": _txt(ide, "cte:modal", _NS_CTE) if ide is not None else None,
        "tomador": tomador,
        "situacao": "autorizada" if prot is not None else "desconhecida",
        "modelo_doc": "cte",
    }


def _parse_res_cte(root: Any) -> Dict[str, Any]:
    """Extrai metadados de resCTe (resumo CT-e)."""
    res = root.find(".//cte:resCTe", _NS_CTE) or root
    return {
        "chave": _txt(res, "cte:chCTe", _NS_CTE),
        "emit_cnpj": _txt(res, "cte:CNPJ", _NS_CTE),
        "dest_cnpj": None,
        "rem_cnpj": None,
        "rec_cnpj": None,
        "valor_total": _txt(res, "cte:vICMSUFDest", _NS_CTE),  # valor disponível no resumo
        "dh_emissao": _txt(res, "cte:dhEmi", _NS_CTE),
        "modal": _txt(res, "cte:modal", _NS_CTE),
        "tomador": None,
        "situacao": "desconhecida",
        "modelo_doc": "cte",
    }


def _parse_evento_cte(root: Any) -> Dict[str, Any]:
    """Extrai metadados de evento CT-e."""
    inf_ev = root.find(".//cte:infEvento", _NS_CTE)
    if inf_ev is None:
        inf_ev = root.find(".//cte:evento/cte:infEvento", _NS_CTE)
    return {
        "chave": _txt(inf_ev, "cte:chCTe", _NS_CTE) if inf_ev is not None else None,
        "emit_cnpj": _txt(inf_ev, "cte:CNPJ", _NS_CTE) if inf_ev is not None else None,
        "dest_cnpj": None,
        "rem_cnpj": None,
        "rec_cnpj": None,
        "valor_total": None,
        "dh_emissao": _txt(inf_ev, "cte:dhEvento", _NS_CTE) if inf_ev is not None else None,
        "modal": None,
        "tomador": None,
        "situacao": "evento",
        "tipo_evento": _txt(inf_ev, "cte:tpEvento", _NS_CTE) if inf_ev is not None else None,
        "modelo_doc": "cte",
    }


_NS_MDFE = {"mdfe": "http://www.portalfiscal.inf.br/mdfe"}


def _parse_proc_mdfe(root: Any) -> Dict[str, Any]:
    """Extrai metadados de procMDFe (MDF-e completo autorizado)."""
    mdfe = root.find(".//mdfe:MDFe", _NS_MDFE)
    inf = mdfe.find("mdfe:infMDFe", _NS_MDFE) if mdfe is not None else None
    if inf is None:
        return {}

    ide = inf.find("mdfe:ide", _NS_MDFE)
    emit = inf.find("mdfe:emit", _NS_MDFE)
    tot = inf.find("mdfe:tot", _NS_MDFE)
    prot = root.find(".//mdfe:protMDFe/mdfe:infProt", _NS_MDFE)

    qtd_cte = _txt(tot, "mdfe:qCTe", _NS_MDFE) if tot is not None else None
    qtd_nfe = _txt(tot, "mdfe:qNFe", _NS_MDFE) if tot is not None else None

    return {
        "chave": inf.get("Id", "").replace("MDFe", ""),
        "emit_cnpj": _txt(emit, "mdfe:CNPJ", _NS_MDFE) if emit is not None else None,
        "dest_cnpj": None,
        "valor_total": _txt(tot, "mdfe:vCarga", _NS_MDFE) if tot is not None else None,
        "dh_emissao": _txt(ide, "mdfe:dhEmi", _NS_MDFE) if ide is not None else None,
        "situacao": "autorizada" if prot is not None else "desconhecida",
        "modal": _txt(ide, "mdfe:modal", _NS_MDFE) if ide is not None else None,
        "mdfe_uf_ini": _txt(ide, "mdfe:UFIni", _NS_MDFE) if ide is not None else None,
        "mdfe_uf_fim": _txt(ide, "mdfe:UFFim", _NS_MDFE) if ide is not None else None,
        "mdfe_qtd_cte": int(qtd_cte) if qtd_cte else None,
        "mdfe_qtd_nfe": int(qtd_nfe) if qtd_nfe else None,
        "modelo_doc": "mdfe",
    }


def _parse_res_mdfe(root: Any) -> Dict[str, Any]:
    """Extrai metadados de resMDFe (resumo MDF-e)."""
    res = root.find(".//mdfe:resMDFe", _NS_MDFE) or root
    return {
        "chave": _txt(res, "mdfe:chMDFe", _NS_MDFE),
        "emit_cnpj": _txt(res, "mdfe:CNPJ", _NS_MDFE),
        "dest_cnpj": None,
        "valor_total": None,
        "dh_emissao": _txt(res, "mdfe:dhEmi", _NS_MDFE),
        "modal": _txt(res, "mdfe:modal", _NS_MDFE),
        "situacao": "desconhecida",
        "modelo_doc": "mdfe",
    }


def _parse_evento_mdfe(root: Any) -> Dict[str, Any]:
    """Extrai metadados de evento MDF-e."""
    inf_ev = root.find(".//mdfe:infEvento", _NS_MDFE)
    if inf_ev is None:
        inf_ev = root.find(".//mdfe:evento/mdfe:infEvento", _NS_MDFE)
    return {
        "chave": _txt(inf_ev, "mdfe:chMDFe", _NS_MDFE) if inf_ev is not None else None,
        "emit_cnpj": _txt(inf_ev, "mdfe:CNPJ", _NS_MDFE) if inf_ev is not None else None,
        "dest_cnpj": None,
        "valor_total": None,
        "dh_emissao": _txt(inf_ev, "mdfe:dhEvento", _NS_MDFE) if inf_ev is not None else None,
        "situacao": "evento",
        "tipo_evento": _txt(inf_ev, "mdfe:tpEvento", _NS_MDFE) if inf_ev is not None else None,
        "modelo_doc": "mdfe",
    }


def _classify_schema(schema: str) -> str:
    s = schema.lower()
    if "procnfe" in s or "proccte" in s or "procmdfe" in s:
        return "completo"
    if "resnfe" in s or "rescte" in s or "resmdfe" in s:
        return "resumo"
    if "evento" in s or "procevento" in s:
        return "evento"
    return "desconhecido"


def parse_doczip(schema: str, b64_content: str) -> Dict[str, Any]:
    """Descomprime e extrai metadados de um docZip do SEFAZ.

    Retorna dict com: tipo, chave, emit_cnpj, dest_cnpj, valor_total,
    dh_emissao, situacao, sha256, xml_bytes e campos CT-e quando aplicável.
    """
    try:
        xml_bytes = decompress_doczip(b64_content)
    except Exception as exc:
        raise ValueError(f"Falha ao descomprimir docZip (schema={schema}): {exc}") from exc

    sha = sha256_of(xml_bytes)
    tipo = _classify_schema(schema)

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"XML inválido no docZip (schema={schema}): {exc}") from exc

    s = schema.lower()
    if "procnfe" in s:
        meta = _parse_proc_nfe(root)
    elif "resnfe" in s:
        meta = _parse_res_nfe(root)
    elif "proccte" in s:
        meta = _parse_proc_cte(root)
    elif "rescte" in s:
        meta = _parse_res_cte(root)
    elif "eventocte" in s or "procevento" in s and "cte" in s:
        meta = _parse_evento_cte(root)
    elif "procmdfe" in s:
        meta = _parse_proc_mdfe(root)
    elif "resmdfe" in s:
        meta = _parse_res_mdfe(root)
    elif "eventomdfe" in s or "procevento" in s and "mdfe" in s:
        meta = _parse_evento_mdfe(root)
    elif "evento" in s:
        meta = _parse_evento(root)
    else:
        logger.warning("Schema desconhecido: %s — salvando sem metadados", schema)
        meta = {}

    return {
        "tipo": tipo,
        "schema_xsd": schema,
        "sha256": sha,
        "xml_bytes": xml_bytes,
        **{k: v for k, v in meta.items() if k != "ibscbs"},
        "ibscbs": meta.get("ibscbs"),
    }
