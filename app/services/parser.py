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


def _parse_itens_nfe(inf: Any) -> list:
    """Extrai lista de itens da NF-e com campos fiscais por item."""
    itens = []
    for det in inf.findall("nfe:det", _NS):
        prod = det.find("nfe:prod", _NS)
        imp = det.find("nfe:imposto", _NS)
        if prod is None:
            continue

        def _imp_val(tag: str) -> Optional[str]:
            if imp is None:
                return None
            el = imp.find(f".//{_NS['nfe'].join(['{', '}'])}{tag}", _NS)
            if el is None:
                el = imp.find(f"nfe:{tag}", _NS)
            return el.text.strip() if el is not None and el.text else None

        # ICMS — vICMS pode estar em vários grupos (ICMS00, ICMS10, ICMSSN102...)
        v_icms = None
        icms_grupo = imp.find(".//nfe:ICMS", _NS) if imp is not None else None
        if icms_grupo is not None:
            for child in icms_grupo:
                val = _txt(child, "nfe:vICMS")
                if val:
                    v_icms = val
                    break

        # IPI
        v_ipi = None
        ipi = imp.find("nfe:IPI", _NS) if imp is not None else None
        if ipi is not None:
            for ipi_trib in ipi:
                val = _txt(ipi_trib, "nfe:vIPI")
                if val:
                    v_ipi = val
                    break

        # PIS/COFINS
        v_pis = None
        pis_g = imp.find("nfe:PIS", _NS) if imp is not None else None
        if pis_g is not None:
            for pg in pis_g:
                val = _txt(pg, "nfe:vPIS")
                if val:
                    v_pis = val
                    break

        v_cofins = None
        cof_g = imp.find("nfe:COFINS", _NS) if imp is not None else None
        if cof_g is not None:
            for cg in cof_g:
                val = _txt(cg, "nfe:vCOFINS")
                if val:
                    v_cofins = val
                    break

        itens.append({
            "nitem": det.get("nItem"),
            "cprod": _txt(prod, "nfe:cProd"),
            "xprod": _txt(prod, "nfe:xProd"),
            "ncm": _txt(prod, "nfe:NCM"),
            "cfop": _txt(prod, "nfe:CFOP"),
            "ucom": _txt(prod, "nfe:uCom"),
            "qcom": _txt(prod, "nfe:qCom"),
            "v_un_com": _txt(prod, "nfe:vUnCom"),
            "v_prod": _txt(prod, "nfe:vProd"),
            "v_frete": _txt(prod, "nfe:vFrete"),
            "v_desc": _txt(prod, "nfe:vDesc"),
            "v_icms": v_icms,
            "v_ipi": v_ipi,
            "v_pis": v_pis,
            "v_cofins": v_cofins,
            "gtin": _txt(prod, "nfe:cEAN"),
        })
    return itens


def _parse_duplicatas_nfe(inf: Any) -> list:
    """Extrai duplicatas (<cobr><dup>) para parcelamento do título a pagar."""
    dups = []
    cobr = inf.find("nfe:cobr", _NS)
    if cobr is None:
        return dups
    for dup in cobr.findall("nfe:dup", _NS):
        dups.append({
            "ndup": _txt(dup, "nfe:nDup"),
            "dvenc": _txt(dup, "nfe:dVenc"),
            "vdup": _txt(dup, "nfe:vDup"),
        })
    return dups


def _parse_proc_nfe(root: Any) -> Dict[str, Any]:
    nfe = root.find(".//nfe:NFe", _NS)
    inf = nfe.find("nfe:infNFe", _NS) if nfe is not None else None
    if inf is None:
        return {}

    emit = inf.find("nfe:emit", _NS)
    dest = inf.find("nfe:dest", _NS)
    ide = inf.find("nfe:ide", _NS)
    total = inf.find("nfe:total/nfe:ICMSTot", _NS)
    ender_emit = emit.find("nfe:enderEmit", _NS) if emit is not None else None

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

    # Número e série extraídos do IDE (mais confiável que extrair da chave)
    numero = _txt(ide, "nfe:nNF") if ide is not None else None
    serie = _txt(ide, "nfe:serie") if ide is not None else None

    return {
        "chave": inf.get("Id", "").replace("NFe", ""),
        "emit_cnpj": emit_cnpj,
        "emit_razao_social": _txt(emit, "nfe:xNome") if emit is not None else None,
        "emit_ie": _txt(emit, "nfe:IE") if emit is not None else None,
        "emit_xlogradouro": _txt(ender_emit, "nfe:xLgr") if ender_emit is not None else None,
        "emit_xmun": _txt(ender_emit, "nfe:xMun") if ender_emit is not None else None,
        "emit_uf": _txt(ender_emit, "nfe:UF") if ender_emit is not None else None,
        "emit_cep": _txt(ender_emit, "nfe:CEP") if ender_emit is not None else None,
        "dest_cnpj": dest_cnpj or dest_cpf,
        "numero": numero,
        "serie": serie,
        "valor_total": _txt(total, "nfe:vNF") if total is not None else None,
        "v_prod": _txt(total, "nfe:vProd") if total is not None else None,
        "v_frete": _txt(total, "nfe:vFrete") if total is not None else None,
        "v_seg": _txt(total, "nfe:vSeg") if total is not None else None,
        "v_desc": _txt(total, "nfe:vDesc") if total is not None else None,
        "v_ipi": _txt(total, "nfe:vIPI") if total is not None else None,
        "v_icms": _txt(total, "nfe:vICMS") if total is not None else None,
        "v_pis": _txt(total, "nfe:vPIS") if total is not None else None,
        "v_cofins": _txt(total, "nfe:vCOFINS") if total is not None else None,
        "itens": _parse_itens_nfe(inf),
        "duplicatas": _parse_duplicatas_nfe(inf),
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
        # resNFe inclui xNome (razão social do emitente); número/série só no completo
        "emit_razao_social": _txt(res, "nfe:xNome") or None,
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

    import json as _json
    # Serializar itens e duplicatas como JSON string para armazenar na coluna Text
    itens = meta.pop("itens", None)
    duplicatas = meta.pop("duplicatas", None)

    return {
        "tipo": tipo,
        "schema_xsd": schema,
        "sha256": sha,
        "xml_bytes": xml_bytes,
        **{k: v for k, v in meta.items() if k != "ibscbs"},
        "ibscbs": meta.get("ibscbs"),
        "itens_json": _json.dumps(itens, ensure_ascii=False) if itens else None,
        "duplicatas_json": _json.dumps(duplicatas, ensure_ascii=False) if duplicatas else None,
    }
