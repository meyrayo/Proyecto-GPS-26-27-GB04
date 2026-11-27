"""Gestor Soporte y Contacto (EP-07 Soporte).

US-14: formulario de contacto. La incidencia queda registrada para que la tienda
haga el seguimiento. No se envía ningún correo y solo se admiten emails de prueba.
"""
import re
import sqlite3
import uuid
from datetime import datetime

from app.repositories import incidencias_repo

FORMATO = "%Y-%m-%d %H:%M:%S"
# Email sintético: formato válido y dominio de prueba terminado en .test (regla de US-14)
PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
DOMINIO_PRUEBA = ".test"
LIMITES = {"nombre": 80, "email": 120, "asunto": 120, "mensaje": 2000}
NOMBRES = {"nombre": "el nombre", "email": "el email", "asunto": "el asunto", "mensaje": "el mensaje"}


class IncidenciaInvalida(Exception):
    """Faltan datos o no son válidos. `errores` indica el campo y qué corregir (US-14-AC-03)."""

    def __init__(self, errores):
        super().__init__("; ".join(errores.values()))
        self.errores = errores


class SoporteNoDisponible(Exception):
    """No se ha podido registrar la incidencia. La interfaz muestra un error y permite reintentar (US-14-AC-05)."""


def nuevoCodigoIncidencia():
    """Código único para un envío del formulario. -> str. US-14-AC-05

    La interfaz lo genera al mostrar el formulario y lo envía con los datos. Si se envía
    dos veces con el mismo código, no se crea otra incidencia.
    """
    return uuid.uuid4().hex


def _validar(incidencia):
    """US-14-AC-02 y AC-03: los cuatro campos son obligatorios y el email debe ser de prueba."""
    datos = {campo: (incidencia.get(campo) or "").strip() for campo in LIMITES}
    datos["email"] = datos["email"].lower()
    errores = {}
    for campo, limite in LIMITES.items():
        if not datos[campo]:
            errores[campo] = f"Escribe {NOMBRES[campo]}."
        elif len(datos[campo]) > limite:
            errores[campo] = f"{NOMBRES[campo].capitalize()} no puede tener más de {limite} caracteres."
    if "email" not in errores:
        if not PATRON_EMAIL.match(datos["email"]):
            errores["email"] = "El email no tiene un formato válido. Ejemplo: frodo@comarca.test"
        elif not datos["email"].endswith(DOMINIO_PRUEBA):
            errores["email"] = "Usa un email de prueba que termine en .test, por ejemplo frodo@comarca.test"
    return errores, datos


def reportarIncidencia(incidencia, ahora=None):
    """Registra una incidencia del formulario de contacto y devuelve su id. -> int. US-14

    En el diagrama devuelve bool; aquí devuelve el id de la incidencia registrada.
    `incidencia` es un diccionario con nombre, email, asunto, mensaje y codigo,
    tal y como llegan del formulario.
    `ahora` permite fijar la hora en las pruebas; por defecto, la hora local de la tienda.
    Lanza IncidenciaInvalida con el campo y el motivo de cada error (US-14-AC-03)
    y SoporteNoDisponible si falla el registro (US-14-AC-05). En los dos casos no se guarda nada.
    Con el mismo código devuelve la incidencia ya registrada y no crea otra (US-14-AC-05).
    No se envía ningún correo (US-14-AC-06).
    """
    ahora = ahora or datetime.now()
    errores, datos = _validar(incidencia)
    if errores:
        raise IncidenciaInvalida(errores)
    codigo = (incidencia.get("codigo") or "").strip() or nuevoCodigoIncidencia()
    try:
        return incidencias_repo.crear(codigo, datos["nombre"], datos["email"], datos["asunto"],
                                      datos["mensaje"], ahora.strftime(FORMATO))
    except sqlite3.Error as error:
        raise SoporteNoDisponible("No se ha podido registrar el mensaje") from error
