"""Gestor Usuario (EP-04 Usuarios).

US-09: alta con invitación de un solo uso, verificación simulada e inicio de sesión.
La contraseña se guarda con un hash seguro (werkzeug), nunca en texto plano.
"""
import re
import secrets
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

from app.repositories import usuarios_repo

PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
LONGITUD_MINIMA = 8


class RegistroInvalido(Exception):
    """Los datos del alta no son válidos. `motivos` explica cada problema."""

    def __init__(self, motivos):
        super().__init__("; ".join(motivos))
        self.motivos = motivos


class VerificacionInvalida(Exception):
    """El enlace de verificación no es válido o ya se usó."""


class AccesoDenegado(Exception):
    """No se puede iniciar sesión. El mensaje explica el motivo."""


class UsuariosNoDisponibles(Exception):
    """Fallo al guardar o leer en la base de datos."""


def _validar(datos):
    motivos = []
    codigo = (datos.get("codigo_invitacion") or "").strip()
    email = (datos.get("email") or "").strip().lower()
    nombre = (datos.get("nombre_usuario") or "").strip()
    contrasena = datos.get("contrasena") or ""
    repetida = datos.get("contrasena2") or ""

    invitacion = usuarios_repo.obtener_invitacion(codigo) if codigo else None
    if not codigo:
        motivos.append("Hace falta un código de invitación.")
    elif invitacion is None:
        motivos.append("El código de invitación no existe.")
    elif invitacion["estado"] == "usada":
        motivos.append("La invitación ya se ha utilizado.")
    elif invitacion["estado"] == "revocada":
        motivos.append("La invitación ha sido revocada.")

    if not PATRON_EMAIL.match(email):
        motivos.append("El email no tiene un formato válido.")
    elif usuarios_repo.existe_email(email):
        motivos.append("Ya existe una cuenta con ese email.")

    if not nombre:
        motivos.append("El nombre de usuario es obligatorio.")

    if len(contrasena) < LONGITUD_MINIMA:
        motivos.append(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres.")
    elif contrasena != repetida:
        motivos.append("Las contraseñas no coinciden.")

    return motivos, invitacion, email, nombre, contrasena


def crearUsuario(usuario):
    """Crea una cuenta Cliente pendiente de verificación. US-09-AC-01 a 04

    `usuario` es un diccionario con codigo_invitacion, email, nombre_usuario,
    contrasena y contrasena2. Devuelve el token de verificación simulado
    (lo que iría en el correo). Lanza RegistroInvalido con los motivos si algo falla.
    """
    try:
        motivos, invitacion, email, nombre, contrasena = _validar(usuario)
        if motivos:
            raise RegistroInvalido(motivos)
        token = secrets.token_urlsafe(24)
        usuarios_repo.crear_pendiente(email, nombre, generate_password_hash(contrasena), invitacion["id"], token)
        return token
    except sqlite3.IntegrityError as error:
        # Dos altas a la vez con el mismo email: solo se guarda la primera
        raise RegistroInvalido(["Ya existe una cuenta con ese email."]) from error
    except sqlite3.Error as error:
        raise UsuariosNoDisponibles("No se ha podido completar el registro") from error


def verificarCuenta(token):
    """Activa la cuenta asociada al enlace de verificación simulado. US-09-AC-05 y 06"""
    try:
        fila = usuarios_repo.obtener_por_token(token) if token else None
        if fila is None or fila["estado"] != "pendiente":
            raise VerificacionInvalida("El enlace de verificación no es válido o ya se ha utilizado.")
        usuarios_repo.activar(fila["id"])
        return True
    except sqlite3.Error as error:
        raise UsuariosNoDisponibles("No se ha podido verificar la cuenta") from error


def iniciarSesion(email, contrasena):
    """Comprueba las credenciales. Solo entran las cuentas activas. US-09-AC-05

    Devuelve un diccionario con id, nombre_usuario y rol.
    """
    try:
        fila = usuarios_repo.obtener_por_email((email or "").strip().lower())
    except sqlite3.Error as error:
        raise UsuariosNoDisponibles("No se ha podido iniciar sesión") from error
    if fila is None or not check_password_hash(fila["hash_contrasena"], contrasena or ""):
        raise AccesoDenegado("El email o la contraseña no son correctos.")
    if fila["estado"] == "pendiente":
        raise AccesoDenegado("La cuenta está pendiente de verificación. Usa el enlace del correo de confirmación.")
    if fila["estado"] == "bloqueada":
        raise AccesoDenegado("La cuenta está bloqueada.")
    return {"id": fila["id"], "nombre_usuario": fila["nombre_usuario"], "rol": fila["rol"]}


def getRolUsuario(idUsuario):
    """Rol del usuario, o None si no existe. -> str. Lo usan los métodos @Admin y @Moderador. US-09"""
    fila = usuarios_repo.obtener_por_id(idUsuario)
    return fila["rol"] if fila else None


def cambiarRol(idUsuario, rol):
    """Cambia el rol de un usuario (cliente, moderador, admin). -> bool

    Fuera del alcance de la baseline: las cuentas de Moderador y Administrador se crean
    fuera del registro público (EP-04) y US-10 no pide cambiar roles.
    """
    raise NotImplementedError("Fuera del alcance: los roles de Moderador y Administrador vienen preconfigurados")


# ---------- @Admin (US-10) ----------

class PermisoDenegado(Exception):
    """Solo un administrador puede bloquear y desbloquear cuentas. `motivo` es sin_sesion o no_admin (US-10-AC-05 y AC-06)."""

    def __init__(self, motivo, mensaje):
        super().__init__(mensaje)
        self.motivo = motivo


class CuentaNoValida(Exception):
    """La cuenta no existe o no es una cuenta Cliente que se pueda bloquear o desbloquear. No se cambia nada."""


def _comprobar_admin(idAdmin):
    """US-10-AC-05 y AC-06: sesión iniciada, cuenta activa y rol Administrador. Se comprueba al guardar."""
    try:
        admin = usuarios_repo.obtener_por_id(idAdmin) if idAdmin is not None else None
    except sqlite3.Error as error:
        raise UsuariosNoDisponibles("No se ha podido comprobar la cuenta") from error
    if admin is None:
        raise PermisoDenegado("sin_sesion", "Tu sesión ha caducado. Inicia sesión como administrador.")
    if admin["rol"] != "admin" or admin["estado"] != "activa":
        raise PermisoDenegado("no_admin", "Solo un administrador puede bloquear o desbloquear cuentas.")


def getClientes(idAdmin):
    """@Admin. Cuentas Cliente con id, email, nombre_usuario y estado. -> list. US-10

    La interfaz las muestra con el botón «Bloquear» o «Desbloquear» según su estado.
    """
    _comprobar_admin(idAdmin)
    try:
        return [dict(fila) for fila in usuarios_repo.listar_clientes()]
    except sqlite3.Error as error:
        raise UsuariosNoDisponibles("No se han podido cargar las cuentas") from error


def _cambiar_estado(idUsuario, idAdmin, desde, hasta, accion):
    _comprobar_admin(idAdmin)
    try:
        cuenta = usuarios_repo.obtener_por_id(idUsuario)
        if cuenta is None or cuenta["rol"] != "cliente":
            raise CuentaNoValida(f"Solo se pueden {accion} cuentas de cliente.")
        if usuarios_repo.cambiar_estado_cliente(idUsuario, desde, hasta):
            return True
        # No ha cambiado: se vuelve a leer para informar del estado actual (US-10-AC-07)
        actual = usuarios_repo.obtener_por_id(idUsuario)["estado"]
    except sqlite3.Error as error:
        raise UsuariosNoDisponibles(f"No se ha podido {accion} la cuenta") from error
    if actual == hasta:
        return False
    raise CuentaNoValida("La cuenta está pendiente de verificación y no se puede " + accion + ".")


def banearUsuario(idUsuario, idAdmin):
    """@Admin. Bloquea una cuenta Cliente activa. -> bool. US-10

    En el diagrama es banearUsuario(idUsuario); aquí también recibe el administrador de la sesión,
    porque el permiso se comprueba al guardar. Un Moderador no puede bloquear (US-10-AC-05).
    La cuenta bloqueada no puede iniciar sesión ni participar (US-10-AC-02) y sus sesiones
    abiertas se cierran en la siguiente petición (US-10-AC-03, ver routes/sesion.py).
    Devuelve True si se ha bloqueado ahora y False si ya estaba bloqueada (US-10-AC-07).
    Lanza PermisoDenegado, CuentaNoValida o UsuariosNoDisponibles. En esos casos no se cambia nada.
    """
    return _cambiar_estado(idUsuario, idAdmin, "activa", "bloqueada", "bloquear")


def desbanearUsuario(idUsuario, idAdmin):
    """@Admin. Devuelve una cuenta Cliente bloqueada al estado activo. -> bool. US-10-AC-04

    No borra sus mensajes ni inicia una sesión: el cliente tiene que volver a entrar.
    Devuelve True si se ha desbloqueado ahora y False si ya estaba activa.
    Lanza PermisoDenegado, CuentaNoValida o UsuariosNoDisponibles. En esos casos no se cambia nada.
    """
    return _cambiar_estado(idUsuario, idAdmin, "bloqueada", "activa", "desbloquear")


def cuentaBloqueada(idUsuario):
    """True si la cuenta de la sesión está bloqueada. -> bool. US-10-AC-03

    Lo usa routes/sesion.py en cada petición para cerrar la sesión de una cuenta bloqueada.
    Si no se puede leer la base de datos devuelve False: las operaciones protegidas
    vuelven a comprobar la cuenta al guardar.
    """
    if idUsuario is None:
        return False
    try:
        fila = usuarios_repo.obtener_por_id(idUsuario)
    except sqlite3.Error:
        return False
    return fila is not None and fila["estado"] == "bloqueada"
