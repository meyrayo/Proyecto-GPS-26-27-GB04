"""Crea y configura la aplicación web de El Hogar del Hobbit.

Arquitectura por capas:
    routes/        -> recibe la petición y devuelve la página (capa de presentación)
    gestores/      -> reglas y validaciones (lógica de negocio, según el diagrama de gestores)
    repositories/  -> consultas SQL (acceso a datos)
    database/      -> estructura de las tablas y datos ficticios (SQLite)
    templates/ y static/ -> lo que ve el usuario (frontend)
"""
import importlib
import os
import pkgutil
from pathlib import Path

from flask import Flask, render_template

from app import db

from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # Configuración por defecto. La base de datos vive en la carpeta instance/,
    # que no se sube a GitHub: cada desarrollador tiene la suya.
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "clave-solo-para-desarrollo"),
        DATABASE=os.path.join(app.instance_path, "hobbit.sqlite"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    csrf.init_app(app)
    db.init_app(app)
    _registrar_rutas(app)
    _registrar_errores(app)
    return app


def _registrar_rutas(app):
    """Registra automáticamente cada archivo de app/routes/ que tenga un `bp`.

    Así, cada historia añade su propio archivo de rutas sin tocar este,
    y se evitan conflictos al hacer merge.
    """
    from app import routes

    for modulo in pkgutil.iter_modules(routes.__path__):
        modulo_importado = importlib.import_module(f"{routes.__name__}.{modulo.name}")
        blueprint = getattr(modulo_importado, "bp", None)
        if blueprint is not None:
            app.register_blueprint(blueprint)


def _registrar_errores(app):
    @app.errorhandler(404)
    def no_encontrada(error):
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):
        return render_template("errores/500.html"), 500
