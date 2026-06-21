"""Geração de documentos auxiliares em PDF (DANFE/DACTE/DAMDFE/DANFSE).

Gera o PDF sob demanda a partir do XML armazenado de cada documento — não
depende de PDF servido pelos portais (o SEFAZ não serve DANFE; o ADN serve
DANFSe, mas gerar do XML é uniforme e offline). Usa brazilfiscalreport.
"""

import logging

from app.services.storage import load_xml_doc

logger = logging.getLogger(__name__)


def gerar_pdf(doc) -> bytes:
    """Gera o PDF auxiliar do documento a partir do XML. Levanta ValueError
    se o tipo não suportar geração (resumo/evento) ou em falha de render."""
    tipo = getattr(doc, "tipo", None)
    if tipo != "completo":
        raise ValueError(
            f"PDF disponível apenas para documentos completos (este é '{tipo}'). "
            "Resumos e eventos não têm documento auxiliar."
        )

    xml = load_xml_doc(doc)  # bytes; FileNotFoundError se não houver
    modelo = (getattr(doc, "modelo", "") or "").lower()

    if modelo == "nfse":
        from brazilfiscalreport.danfse import Danfse
        pdf = Danfse(xml=xml).output()
    elif modelo == "cte":
        from brazilfiscalreport.dacte import Dacte
        pdf = Dacte(xml=xml).output()
    elif modelo == "mdfe":
        from brazilfiscalreport.damdfe import Damdfe
        pdf = Damdfe(xml=xml).output()
    else:  # nfe, nfce
        from brazilfiscalreport.danfe import Danfe
        pdf = Danfe(xml=xml).output()

    return bytes(pdf)
