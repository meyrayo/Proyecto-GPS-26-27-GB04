"""Pruebas de la lógica y los datos del formulario de contacto (US-14, GB04-125)."""
import sqlite3
from datetime import datetime

import pytest

from app.db import get_db
from app.gestores import gestor_soporte
from app.repositories import incidencias_repo

HOY = datetime(2026, 11, 21, 18, 30, 0)
VALIDA = {"nombre": "Frodo Bolsón", "email": "Frodo@Comarca.test", "asunto": "Pedido sin llegar",
          "mensaje": "Mi pedido de prueba no aparece.", "codigo": "envio-1"}


def reportar(app, **cambios):
    with app.app_context():
        return gestor_soporte.reportarIncidencia({**VALIDA, **cambios}, ahora=HOY)


def total(app):
    with app.app_context():
        return get_db().execute("SELECT COUNT(*) FROM incidencias").fetchone()[0]


def test_una_incidencia_valida_queda_registrada_para_seguimiento(app):
    """US-14-AC-04 y AC-06."""
    id_incidencia = reportar(app)
    with app.app_context():
        fila = incidencias_repo.obtener_por_codigo("envio-1")
    assert fila["id"] == id_incidencia
    assert (fila["nombre"], fila["email"], fila["asunto"]) == ("Frodo Bolsón", "frodo@comarca.test", "Pedido sin llegar")
    assert fila["estado"] == "registrada" and fila["fecha_hora"] == "2026-11-21 18:30:00"


@pytest.mark.parametrize("campo", ["nombre", "email", "asunto", "mensaje"])
def test_todos_los_campos_son_obligatorios(app, campo):
    """US-14-AC-02 y AC-03."""
    with pytest.raises(gestor_soporte.IncidenciaInvalida) as error:
        reportar(app, **{campo: "   "})
    assert list(error.value.errores) == [campo]
    assert total(app) == 0


@pytest.mark.parametrize("email", ["frodo", "frodo@", "frodo@comarca", "fro do@comarca.test"])
def test_un_email_sin_formato_valido_se_indica(app, email):
    """US-14-AC-03."""
    with pytest.raises(gestor_soporte.IncidenciaInvalida) as error:
        reportar(app, email=email)
    assert "formato válido" in error.value.errores["email"]
    assert total(app) == 0


def test_solo_se_admiten_emails_de_prueba(app):
    """US-14-AC-06: no se aceptan datos personales reales."""
    with pytest.raises(gestor_soporte.IncidenciaInvalida) as error:
        reportar(app, email="frodo@gmail.com")
    assert ".test" in error.value.errores["email"]
    assert total(app) == 0


def test_los_textos_demasiado_largos_se_indican(app):
    with pytest.raises(gestor_soporte.IncidenciaInvalida) as error:
        reportar(app, asunto="a" * 121, mensaje="m" * 2001)
    assert set(error.value.errores) == {"asunto", "mensaje"}
    assert total(app) == 0


def test_el_mismo_envio_dos_veces_no_crea_duplicados(app):
    """US-14-AC-05."""
    primera = reportar(app)
    segunda = reportar(app)
    assert primera == segunda and total(app) == 1


def test_envios_distintos_crean_incidencias_distintas(app):
    reportar(app)
    reportar(app, codigo="envio-2")
    assert total(app) == 2


def test_sin_codigo_se_genera_uno(app):
    reportar(app, codigo="")
    assert total(app) == 1


def test_los_codigos_nuevos_no_se_repiten():
    primer_codigo = gestor_soporte.nuevoCodigoIncidencia()
    segundo_codigo = gestor_soporte.nuevoCodigoIncidencia()
    assert primer_codigo != segundo_codigo


def test_si_falla_el_registro_se_informa_y_se_puede_reintentar(app, monkeypatch):
    """US-14-AC-05."""
    original = incidencias_repo.crear

    def falla(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(incidencias_repo, "crear", falla)
    with pytest.raises(gestor_soporte.SoporteNoDisponible):
        reportar(app)
    assert total(app) == 0
    monkeypatch.setattr(incidencias_repo, "crear", original)
    reportar(app)
    reportar(app)
    assert total(app) == 1
