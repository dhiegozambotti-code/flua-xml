"""Testes do motor de alertas operacionais."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.alertas import alertas_empresa


def _now():
    return datetime.now(timezone.utc)


def _make_cert(status="ativo", dias_restantes=90):
    cert = MagicMock()
    cert.status = status
    cert.id = "cert-1"
    cert.fingerprint = "AA:BB:CC"
    cert.valido_ate = _now() + timedelta(days=dias_restantes)
    return cert


def _make_estado(status="ativo", modelo="nfe", tipo_fluxo="entrada",
                  ultimo_sucesso_horas_atras=None, bloqueado_horas=1):
    estado = MagicMock()
    estado.status = status
    estado.modelo = modelo
    estado.tipo_fluxo = tipo_fluxo
    if status == "bloqueado_656":
        estado.bloqueado_ate = _now() + timedelta(hours=bloqueado_horas)
    else:
        estado.bloqueado_ate = None
    if ultimo_sucesso_horas_atras is not None:
        estado.ultimo_sucesso = _now() - timedelta(hours=ultimo_sucesso_horas_atras)
    else:
        estado.ultimo_sucesso = None
    return estado


def _mock_db(certs, estados):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.side_effect = [certs, estados]
    return db


class TestAlertasCertificado:
    def test_sem_certificado_retorna_alerta_ausente(self):
        db = _mock_db([], [])
        alertas = alertas_empresa(db, "emp-1")
        tipos = [a["tipo"] for a in alertas]
        assert "certificado.ausente" in tipos

    def test_cert_valido_sem_alerta(self):
        db = _mock_db([_make_cert(dias_restantes=60)], [])
        alertas = alertas_empresa(db, "emp-1")
        assert not alertas

    def test_cert_expirando_30_dias_aviso(self):
        db = _mock_db([_make_cert(dias_restantes=25)], [])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "certificado.expirando" and a["severidade"] == "aviso" for a in alertas)

    def test_cert_expirando_7_dias_critico(self):
        db = _mock_db([_make_cert(dias_restantes=5)], [])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "certificado.expirando" and a["severidade"] == "critico" for a in alertas)

    def test_cert_expirado_critico(self):
        db = _mock_db([_make_cert(dias_restantes=-1)], [])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "certificado.expirado" for a in alertas)

    def test_cert_inativo_alerta(self):
        db = _mock_db([_make_cert(status="revogado", dias_restantes=60)], [])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "certificado.inativo" for a in alertas)


class TestAlertasDistribuicao:
    def test_bloqueado_656_retorna_alerta(self):
        db = _mock_db([_make_cert()], [_make_estado(status="bloqueado_656")])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "distribuicao.bloqueada_656" for a in alertas)

    def test_cert_invalido_retorna_alerta(self):
        db = _mock_db([_make_cert()], [_make_estado(status="cert_invalido")])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "distribuicao.cert_invalido" for a in alertas)

    def test_sem_polling_3h_retorna_aviso(self):
        db = _mock_db([_make_cert()], [_make_estado(status="ativo", ultimo_sucesso_horas_atras=3)])
        alertas = alertas_empresa(db, "emp-1")
        assert any(a["tipo"] == "distribuicao.sem_polling" for a in alertas)

    def test_polling_recente_sem_alerta(self):
        db = _mock_db([_make_cert()], [_make_estado(status="ativo", ultimo_sucesso_horas_atras=1)])
        alertas = alertas_empresa(db, "emp-1")
        sem_polling = [a for a in alertas if a["tipo"] == "distribuicao.sem_polling"]
        assert not sem_polling

    def test_bloqueado_656_detalhe_contem_modelo(self):
        db = _mock_db([_make_cert()], [_make_estado(status="bloqueado_656", modelo="nfe")])
        alertas = alertas_empresa(db, "emp-1")
        alerta = next(a for a in alertas if a["tipo"] == "distribuicao.bloqueada_656")
        assert alerta["detalhe"]["modelo"] == "nfe"
