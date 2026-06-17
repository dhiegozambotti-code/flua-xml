"""Testes da máquina de estados do orquestrador (sem SEFAZ real).

Usa mocks para simular respostas do NFeSoapClient e verifica que os
estados de distribuição são atualizados corretamente após cada cStat.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.orquestrador import _advisory_key, _poll_estado, _store_doc


# ---- helpers ----------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _make_empresa(cnpj="12345678000195", uf="SP", org_id="org-001"):
    e = MagicMock()
    e.id = "emp-001"
    e.cnpj = cnpj
    e.uf = uf
    e.organizacao_id = org_id
    return e


def _make_estado(modelo="nfe", tipo_fluxo="entrada", ult_nsu=0, status="ativo"):
    s = MagicMock()
    s.empresa_id = "emp-001"
    s.modelo = modelo
    s.tipo_fluxo = tipo_fluxo
    s.ult_nsu = ult_nsu
    s.max_nsu = 0
    s.status = status
    s.proximo_polling = None
    s.bloqueado_ate = None
    s.ultimo_sucesso = None
    s.endpoint_usado = None
    return s


def _make_db():
    db = MagicMock()
    db.execute.return_value.scalar.return_value = True  # advisory lock adquirido
    return db


def _resp_138(docs=None, ult_nsu=1, max_nsu=1):
    return {
        "cstat": 138,
        "xmotivo": "Lote de DF-e localizado.",
        "ult_nsu": ult_nsu,
        "max_nsu": max_nsu,
        "docs": docs or [],
    }


def _resp_137():
    return {"cstat": 137, "xmotivo": "Nenhum DF-e localizado.", "ult_nsu": 0, "max_nsu": 0, "docs": []}


def _resp_656():
    return {"cstat": 656, "xmotivo": "Consumo Indevido.", "ult_nsu": 0, "max_nsu": 0, "docs": []}


# ---- testes de máquina de estados ------------------------------------------

class TestAdvisoryKey:
    def test_chave_deterministica(self):
        k1 = _advisory_key("emp-001", "nfe", "entrada")
        k2 = _advisory_key("emp-001", "nfe", "entrada")
        assert k1 == k2

    def test_chave_diferente_por_fluxo(self):
        k_ent = _advisory_key("emp-001", "nfe", "entrada")
        k_sai = _advisory_key("emp-001", "nfe", "saida")
        assert k_ent != k_sai

    def test_chave_diferente_por_modelo(self):
        k_nfe = _advisory_key("emp-001", "nfe", "entrada")
        k_cte = _advisory_key("emp-001", "cte", "entrada")
        assert k_nfe != k_cte


class TestCstat137:
    def test_status_vira_sem_documentos(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient:
            MockClient.return_value.dist_nsu.return_value = _resp_137()
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        assert estado.status == "sem_documentos"

    def test_proximo_polling_em_1h(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        before = _now()
        with patch("app.services.orquestrador.NFeSoapClient") as MockClient:
            MockClient.return_value.dist_nsu.return_value = _resp_137()
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        delta = estado.proximo_polling - before
        assert timedelta(minutes=59) < delta < timedelta(minutes=61)


class TestCstat656:
    def test_status_vira_bloqueado_656(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient, \
             patch("app.services.orquestrador._fire_webhook_656"):
            MockClient.return_value.dist_nsu.return_value = _resp_656()
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        assert estado.status == "bloqueado_656"

    def test_bloqueado_ate_em_1h(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        before = _now()
        with patch("app.services.orquestrador.NFeSoapClient") as MockClient, \
             patch("app.services.orquestrador._fire_webhook_656"):
            MockClient.return_value.dist_nsu.return_value = _resp_656()
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        delta = estado.bloqueado_ate - before
        assert timedelta(minutes=59) < delta < timedelta(minutes=61)

    def test_webhook_disparado(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient, \
             patch("app.services.orquestrador._fire_webhook_656") as mock_wh:
            MockClient.return_value.dist_nsu.return_value = _resp_656()
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        mock_wh.assert_called_once()


class TestCstat138:
    def test_status_ativo_apos_docs(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient, \
             patch("app.services.orquestrador._store_doc") as mock_store, \
             patch("app.services.orquestrador._fire_webhook_captura"), \
             patch("app.services.orquestrador._auto_manifestar"), \
             patch("app.services.orquestrador.parse_doczip") as mock_parse:
            mock_parse.return_value = {"chave": "123", "tipo": "completo"}
            MockClient.return_value.dist_nsu.return_value = _resp_138(
                docs=[{"nsu": 1, "schema": "procNFe_v4.00", "b64": "abc"}],
                ult_nsu=1, max_nsu=1,
            )
            with patch("app.services.orquestrador._doc_exists", return_value=False):
                _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        assert estado.status == "ativo"
        assert estado.ult_nsu == 1

    def test_nsu_ja_existe_nao_duplica(self):
        db = _make_db()
        estado = _make_estado()
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient, \
             patch("app.services.orquestrador._store_doc") as mock_store, \
             patch("app.services.orquestrador._doc_exists", return_value=True):
            MockClient.return_value.dist_nsu.return_value = _resp_138(
                docs=[{"nsu": 1, "schema": "procNFe_v4.00", "b64": "abc"}],
                ult_nsu=1, max_nsu=1,
            )
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")

        mock_store.assert_not_called()


class TestSkipQuandoBloqueado:
    def test_nao_chama_sefaz_se_proximo_polling_futuro(self):
        db = _make_db()
        estado = _make_estado()
        estado.proximo_polling = _now() + timedelta(hours=1)
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient:
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")
            MockClient.assert_not_called()

    def test_nao_chama_sefaz_se_cert_invalido(self):
        db = _make_db()
        estado = _make_estado(status="cert_invalido")
        empresa = _make_empresa()

        with patch("app.services.orquestrador.NFeSoapClient") as MockClient:
            _poll_estado(db, estado, empresa, pfx_bytes=b"pfx", senha="1234")
            MockClient.assert_not_called()
