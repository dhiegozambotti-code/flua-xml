"""Fixtures compartilhadas entre os testes."""

import base64
import gzip

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base


# ---- DB em memória (SQLite) para testes rápidos ----------------------------

@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # SQLite não suporta advisory locks — stub para testes de orquestrador
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


# ---- Helpers XML ------------------------------------------------------------

def build_doczip(xml_str: str) -> str:
    """Comprime XML e retorna Base64 como o SEFAZ retornaria."""
    compressed = gzip.compress(xml_str.encode("utf-8"))
    return base64.b64encode(compressed).decode()


# ---- XMLs sintéticos --------------------------------------------------------

PROC_NFE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
  <NFe>
    <infNFe Id="NFe35260512345678000195550010000000011000000019">
      <ide>
        <mod>55</mod>
        <dhEmi>2026-06-15T10:00:00-03:00</dhEmi>
      </ide>
      <emit><CNPJ>12345678000195</CNPJ></emit>
      <dest><CNPJ>98765432000100</CNPJ></dest>
      <total><ICMSTot><vNF>1500.00</vNF></ICMSTot></total>
    </infNFe>
  </NFe>
  <protNFe><infProt><cStat>100</cStat></infProt></protNFe>
</nfeProc>"""

RES_NFE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<resNFe xmlns="http://www.portalfiscal.inf.br/nfe">
  <chNFe>35260512345678000195550010000000011000000019</chNFe>
  <CNPJ>12345678000195</CNPJ>
  <vNF>1500.00</vNF>
  <dhEmi>2026-06-15T10:00:00-03:00</dhEmi>
  <digVal>abc</digVal>
</resNFe>"""

PROC_NFE_NFC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
  <NFe>
    <infNFe Id="NFe35260512345678000195650010000000011000000019">
      <ide>
        <mod>65</mod>
        <dhEmi>2026-06-15T11:00:00-03:00</dhEmi>
      </ide>
      <emit><CNPJ>12345678000195</CNPJ></emit>
      <total><ICMSTot><vNF>250.00</vNF></ICMSTot></total>
    </infNFe>
  </NFe>
  <protNFe><infProt><cStat>100</cStat></infProt></protNFe>
</nfeProc>"""

PROC_CTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cteProc xmlns="http://www.portalfiscal.inf.br/cte">
  <CTe>
    <infCte Id="CTe35260512345678000195570010000000011000000019">
      <ide>
        <dhEmi>2026-06-15T12:00:00-03:00</dhEmi>
        <modal>01</modal>
        <toma3><toma>3</toma></toma3>
      </ide>
      <emit><CNPJ>12345678000195</CNPJ></emit>
      <dest><CNPJ>98765432000100</CNPJ></dest>
      <rem><CNPJ>11111111000191</CNPJ></rem>
      <receb><CNPJ>22222222000100</CNPJ></receb>
      <vPrest><vTPrest>3000.00</vTPrest></vPrest>
    </infCte>
  </CTe>
  <protCTe><infProt><cStat>100</cStat></infProt></protCTe>
</cteProc>"""

PROC_MDFE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mdfeProc xmlns="http://www.portalfiscal.inf.br/mdfe">
  <MDFe>
    <infMDFe Id="MDFe35260512345678000195580010000000011000000019">
      <ide>
        <dhEmi>2026-06-15T08:00:00-03:00</dhEmi>
        <modal>01</modal>
        <UFIni>SP</UFIni>
        <UFFim>RJ</UFFim>
      </ide>
      <emit><CNPJ>12345678000195</CNPJ></emit>
      <tot>
        <vCarga>50000.00</vCarga>
        <qCTe>5</qCTe>
        <qNFe>20</qNFe>
      </tot>
    </infMDFe>
  </MDFe>
  <protMDFe><infProt><cStat>100</cStat></infProt></protMDFe>
</mdfeProc>"""
