"""Testes do parser de docZip (NF-e, NFC-e, CT-e, MDF-e)."""

import pytest

from app.services.parser import parse_doczip, sha256_of, decompress_doczip
from tests.conftest import (
    build_doczip,
    PROC_NFE_XML,
    RES_NFE_XML,
    PROC_NFE_NFC_XML,
    PROC_CTE_XML,
    PROC_MDFE_XML,
    NFSE_NACIONAL_XML,
)


# ---- helpers ----------------------------------------------------------------

def doczip(xml_str, schema):
    return parse_doczip(schema, build_doczip(xml_str))


# ---- NFS-e evento de cancelamento (101101) ----------------------------------

EVENTO_CANC_NFSE_XML = """<?xml version="1.0" encoding="utf-8"?>
<evento versao="1.01" xmlns="http://www.sped.fazenda.gov.br/nfse">
<infEvento Id="EVT35503081261990572000150000000000000426068815316479101101001">
<nDFSe>4</nDFSe><dhProc>2026-06-01T00:00:00-03:00</dhProc>
<pedRegEvento versao="1.01"><infPedReg Id="PRE101101">
<dhEvento>2026-06-01T00:00:00-03:00</dhEvento>
<chNFSe>35503081261990572000150000000000000426068815316479</chNFSe>
<e101101><xDesc>Cancelamento de NFS-e</xDesc><cMotivo>9</cMotivo></e101101>
</infPedReg></pedRegEvento></infEvento></evento>"""


class TestEventoCancelamentoNfse:
    def test_tipo_evento_cancelamento(self):
        r = doczip(EVENTO_CANC_NFSE_XML, "eventonfse")
        assert r["tipo"] == "evento"
        assert r["tipo_evento"] == "101101"

    def test_chave_referenciada(self):
        r = doczip(EVENTO_CANC_NFSE_XML, "eventonfse")
        assert r["chave"] == "35503081261990572000150000000000000426068815316479"


# ---- NFS-e Nacional (ADN) ---------------------------------------------------

class TestNfseNacional:
    def test_modelo_doc(self):
        r = doczip(NFSE_NACIONAL_XML, "nfse")
        assert r["modelo_doc"] == "nfse"
        assert r["tipo"] == "completo"

    def test_chave_50_digitos(self):
        r = doczip(NFSE_NACIONAL_XML, "nfse")
        assert r["chave"] == "35260612345678000199000000000000123456789012345678"
        assert len(r["chave"]) == 50

    def test_prestador_vira_emit(self):
        r = doczip(NFSE_NACIONAL_XML, "nfse")
        assert r["emit_cnpj"] == "12345678000199"
        assert r["emit_razao_social"] == "PRESTADOR SERVICOS LTDA"

    def test_tomador_vira_dest(self):
        r = doczip(NFSE_NACIONAL_XML, "nfse")
        assert r["dest_cnpj"] == "98765432000188"

    def test_valor_e_situacao(self):
        r = doczip(NFSE_NACIONAL_XML, "nfse")
        assert r["valor_total"] == "1500.00"
        assert r["situacao"] == "autorizada"

    def test_itens_servico_iss(self):
        import json
        r = doczip(NFSE_NACIONAL_XML, "nfse")
        itens = json.loads(r["itens_json"])
        assert itens[0]["cod_trib_nac"] == "010701"
        assert itens[0]["v_iss"] == "75.00"
        assert itens[0]["competencia"] == "2026-06-01"


# ---- NF-e completo ----------------------------------------------------------

class TestProcNFe:
    def test_tipo_completo(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["tipo"] == "completo"

    def test_chave(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["chave"] == "35260512345678000195550010000000011000000019"

    def test_emit_cnpj(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["emit_cnpj"] == "12345678000195"

    def test_dest_cnpj(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["dest_cnpj"] == "98765432000100"

    def test_valor_total(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["valor_total"] == "1500.00"

    def test_situacao_autorizada(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["situacao"] == "autorizada"

    def test_modelo_doc_nfe(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert r["modelo_doc"] == "nfe"

    def test_sha256_presente(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert len(r["sha256"]) == 64

    def test_xml_bytes_presente(self):
        r = doczip(PROC_NFE_XML, "procNFe_v4.00")
        assert b"NFe" in r["xml_bytes"]


# ---- NFC-e (mod=65) ---------------------------------------------------------

class TestNFCe:
    def test_modelo_doc_nfce(self):
        r = doczip(PROC_NFE_NFC_XML, "procNFe_v4.00")
        assert r["modelo_doc"] == "nfce"

    def test_chave_nfce(self):
        r = doczip(PROC_NFE_NFC_XML, "procNFe_v4.00")
        assert r["chave"] == "35260512345678000195650010000000011000000019"


# ---- resNFe (resumo) --------------------------------------------------------

class TestResNFe:
    def test_tipo_resumo(self):
        r = doczip(RES_NFE_XML, "resNFe_v1.01")
        assert r["tipo"] == "resumo"

    def test_chave_resumo(self):
        r = doczip(RES_NFE_XML, "resNFe_v1.01")
        assert r["chave"] == "35260512345678000195550010000000011000000019"

    def test_sem_dest_cnpj(self):
        r = doczip(RES_NFE_XML, "resNFe_v1.01")
        assert r["dest_cnpj"] is None


# ---- CT-e completo ----------------------------------------------------------

class TestProcCTe:
    def test_tipo_completo(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["tipo"] == "completo"

    def test_modelo_doc_cte(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["modelo_doc"] == "cte"

    def test_chave(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["chave"] == "35260512345678000195570010000000011000000019"

    def test_modal_rodoviario(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["modal"] == "01"

    def test_tomador(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["tomador"] == "3"  # destinatário

    def test_rem_cnpj(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["rem_cnpj"] == "11111111000191"

    def test_rec_cnpj(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["rec_cnpj"] == "22222222000100"

    def test_valor_total(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["valor_total"] == "3000.00"

    def test_situacao_autorizada(self):
        r = doczip(PROC_CTE_XML, "procCTe_v4.00")
        assert r["situacao"] == "autorizada"


# ---- MDF-e ------------------------------------------------------------------

class TestProcMDFe:
    def test_tipo_completo(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["tipo"] == "completo"

    def test_modelo_doc_mdfe(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["modelo_doc"] == "mdfe"

    def test_chave(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["chave"] == "35260512345678000195580010000000011000000019"

    def test_emit_cnpj(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["emit_cnpj"] == "12345678000195"

    def test_uf_ini_fim(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["mdfe_uf_ini"] == "SP"
        assert r["mdfe_uf_fim"] == "RJ"

    def test_qtd_docs(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["mdfe_qtd_cte"] == 5
        assert r["mdfe_qtd_nfe"] == 20

    def test_valor_carga(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["valor_total"] == "50000.00"

    def test_situacao_autorizada(self):
        r = doczip(PROC_MDFE_XML, "procMDFe_v3.00")
        assert r["situacao"] == "autorizada"


# ---- Erros ------------------------------------------------------------------

class TestErros:
    def test_b64_invalido_levanta_valueerror(self):
        with pytest.raises(ValueError, match="Falha ao descomprimir"):
            parse_doczip("procNFe_v4.00", "nao-e-base64!!!")

    def test_xml_invalido_levanta_valueerror(self):
        import base64, gzip
        corrupto = base64.b64encode(gzip.compress(b"isto nao e xml")).decode()
        with pytest.raises(ValueError, match="XML inválido"):
            parse_doczip("procNFe_v4.00", corrupto)

    def test_schema_desconhecido_retorna_sem_meta(self):
        r = doczip(PROC_NFE_XML, "schemaEsoterico_v1.00")
        # tipo = desconhecido mas sha256 e xml_bytes presentes
        assert r["tipo"] == "desconhecido"
        assert r["sha256"]
