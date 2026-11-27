"""Pruebas de la lógica y los datos de simular compra (US-17, GB04-107)."""
import sqlite3
from datetime import datetime

import pytest

from app.db import get_db
from app.gestores import gestor_catalogo
from app.repositories import pedidos_repo

HOY = datetime(2026, 11, 18, 17, 30, 0)
ADMIN = 1
COLONOS = 1      # 39,95 €, 12 unidades
SOBRE = 2        # 4,50 €, 80 unidades
PUENTE = 5       # 24,50 €, 3 unidades
AGOTADO = 4      # 0 unidades
RETIRADO = 10    # no publicado, 2 unidades
METODO = "tarjeta_demo"


def comprar(app, cesta, metodo=METODO, codigo="checkout-1", id_usuario=None):
    with app.app_context():
        return gestor_catalogo.realizarCompra(cesta, metodo, codigo, id_usuario, ahora=HOY)


def stock(app, id_producto):
    with app.app_context():
        return get_db().execute("SELECT stock FROM productos WHERE id = ?", (id_producto,)).fetchone()[0]


def total_pedidos(app):
    with app.app_context():
        return get_db().execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]


def poner_stock(app, id_producto, unidades):
    with app.app_context():
        get_db().execute("UPDATE productos SET stock = ? WHERE id = ?", (unidades, id_producto))
        get_db().commit()


# ---------- Métodos de pago de demostración (AC-01) ----------

def test_los_metodos_de_pago_son_de_demostracion():
    """US-17-AC-01: no hay proveedores reales ni datos financieros."""
    assert set(gestor_catalogo.METODOS_PAGO) == {"tarjeta_demo", "transferencia_demo", "tienda_demo"}
    assert all("demostración" in nombre for nombre in gestor_catalogo.METODOS_PAGO.values())


@pytest.mark.parametrize("metodo", [None, "", "visa", "tarjeta"])
def test_un_metodo_de_pago_que_no_es_de_demostracion_no_se_acepta(app, metodo):
    """US-17-AC-01."""
    with pytest.raises(gestor_catalogo.CompraInvalida) as error:
        comprar(app, {"1": 1}, metodo=metodo)
    assert error.value.motivo == "metodo_pago"
    assert total_pedidos(app) == 0 and stock(app, COLONOS) == 12


def test_cada_checkout_tiene_un_codigo_distinto():
    primer_codigo = gestor_catalogo.nuevoCodigoCompra()
    segundo_codigo = gestor_catalogo.nuevoCodigoCompra()
    assert primer_codigo != segundo_codigo


# ---------- Compra correcta (AC-02, AC-03 y AC-05) ----------

def test_la_compra_devuelve_el_pedido_con_articulos_cantidades_precios_y_total(app):
    """US-17-AC-02 y AC-03."""
    pedido = comprar(app, {"1": 2, "2": 3})
    assert pedido["numero"] == "PED-00001" and pedido["codigo"] == "checkout-1"
    assert pedido["fecha"] == "18/11/2026" and pedido["hora"] == "17:30"
    assert pedido["metodo_pago"] == "Tarjeta de demostración"
    assert [(l["nombre"], l["cantidad"], l["precio"], l["subtotal"]) for l in pedido["lineas"]] == [
        ("Colonos de la Comarca", 2, 39.95, 79.90), ("Sobre de cartas: Dragones de Bruma", 3, 4.50, 13.50)]
    assert pedido["unidades"] == 5 and pedido["total"] == 93.40


def test_la_compra_descuenta_las_unidades_del_stock(app):
    """US-17-AC-05."""
    comprar(app, {"1": 2, "5": 3})
    assert stock(app, COLONOS) == 10 and stock(app, PUENTE) == 0


def test_comprar_las_ultimas_unidades_deja_el_producto_agotado(app):
    """US-17-AC-05: el stock llega a 0 y nunca baja de 0."""
    comprar(app, {"5": 3})
    with app.app_context():
        assert gestor_catalogo.getProducto(PUENTE)["estado"] == "Agotado"


def test_el_pedido_guarda_el_usuario_si_hay_sesion(app):
    comprar(app, {"1": 1}, id_usuario=ADMIN)
    with app.app_context():
        assert get_db().execute("SELECT usuario_id FROM pedidos").fetchone()[0] == ADMIN


def test_sin_sesion_o_con_una_cuenta_que_ya_no_existe_tambien_se_compra(app):
    """El checkout simulado no exige cuenta."""
    comprar(app, {"1": 1}, codigo="a")
    comprar(app, {"1": 1}, codigo="b", id_usuario=999)
    with app.app_context():
        assert [f[0] for f in get_db().execute("SELECT usuario_id FROM pedidos")] == [None, None]


def test_el_resultado_no_cambia_aunque_cambie_el_catalogo(app):
    comprar(app, {"1": 1})
    with app.app_context():
        get_db().execute("UPDATE productos SET precio = 99, nombre = 'Otro nombre' WHERE id = 1")
        get_db().commit()
        pedido = gestor_catalogo.getPedido("checkout-1")
    assert pedido["lineas"][0]["nombre"] == "Colonos de la Comarca" and pedido["total"] == 39.95


def test_un_pedido_que_no_existe_devuelve_none(app):
    with app.app_context():
        assert gestor_catalogo.getPedido("no-existe") is None


# ---------- Artículos que no se pueden comprar (AC-04) ----------

@pytest.mark.parametrize("cesta, producto", [
    ({"1": 1, "4": 1}, AGOTADO),
    ({"1": 1, "10": 1}, RETIRADO),
    ({"1": 1, "5": 4}, PUENTE),
])
def test_un_articulo_inactivo_o_sin_stock_no_crea_pedido_ni_toca_el_stock(app, cesta, producto):
    """US-17-AC-04."""
    antes = {COLONOS: stock(app, COLONOS), producto: stock(app, producto)}
    with pytest.raises(gestor_catalogo.CompraInvalida) as error:
        comprar(app, cesta)
    assert error.value.motivo == "no_disponible"
    assert [linea["id"] for linea in error.value.lineas] == [producto]
    assert total_pedidos(app) == 0
    assert {COLONOS: stock(app, COLONOS), producto: stock(app, producto)} == antes


def test_si_el_stock_baja_justo_antes_de_guardar_no_se_toca_nada(app, monkeypatch):
    """US-17-AC-04 y AC-05: el stock se comprueba otra vez dentro de la operación de guardado."""
    original = gestor_catalogo.getCesta

    def cesta_antigua(cesta):
        datos = original(cesta)
        poner_stock(app, PUENTE, 1)   # otra compra se lleva unidades entre el resumen y la confirmación
        return datos

    monkeypatch.setattr(gestor_catalogo, "getCesta", cesta_antigua)
    with pytest.raises(gestor_catalogo.CompraInvalida) as error:
        comprar(app, {"1": 2, "5": 3})
    assert "«El Último Puente»" in str(error.value)
    assert stock(app, COLONOS) == 12 and stock(app, PUENTE) == 1 and total_pedidos(app) == 0


def test_la_cesta_vacia_no_se_puede_comprar(app):
    with pytest.raises(gestor_catalogo.CompraInvalida) as error:
        comprar(app, {})
    assert error.value.motivo == "cesta_vacia" and total_pedidos(app) == 0


@pytest.mark.parametrize("codigo", [None, "", "   ", "x" * 65])
def test_un_codigo_de_checkout_no_valido_no_se_acepta(app, codigo):
    with pytest.raises(gestor_catalogo.CompraInvalida) as error:
        comprar(app, {"1": 1}, codigo=codigo)
    assert error.value.motivo == "codigo" and total_pedidos(app) == 0


# ---------- Error al guardar (AC-06) ----------

def test_si_falla_el_guardado_avisa_y_se_puede_reintentar(app, monkeypatch):
    """US-17-AC-06."""
    original = pedidos_repo.crear

    def falla(*args):
        raise sqlite3.OperationalError("disco lleno")

    monkeypatch.setattr(pedidos_repo, "crear", falla)
    with pytest.raises(gestor_catalogo.CatalogoNoDisponible):
        comprar(app, {"1": 2})
    assert stock(app, COLONOS) == 12 and total_pedidos(app) == 0
    # Al reintentar con el mismo código, la compra se completa
    monkeypatch.setattr(pedidos_repo, "crear", original)
    assert comprar(app, {"1": 2})["total"] == 79.90


def test_si_falla_a_mitad_de_guardar_se_deshace_el_stock(app, monkeypatch):
    """US-17-AC-06: si falla al guardar las líneas, no queda ningún stock descontado."""
    with app.app_context():
        db = get_db()

        class ConexionQueFalla:
            def __getattr__(self, nombre):
                return getattr(db, nombre)

            def executemany(self, *args):
                raise sqlite3.OperationalError("fallo al guardar las líneas")

        monkeypatch.setattr(pedidos_repo, "get_db", lambda: ConexionQueFalla())
        with pytest.raises(gestor_catalogo.CatalogoNoDisponible):
            gestor_catalogo.realizarCompra({"1": 2}, METODO, "checkout-1", ahora=HOY)
    assert stock(app, COLONOS) == 12 and total_pedidos(app) == 0


# ---------- Confirmar dos veces (AC-07) ----------

def test_confirmar_otra_vez_devuelve_el_mismo_pedido_sin_descontar_mas(app):
    """US-17-AC-07."""
    primero = comprar(app, {"1": 2})
    segundo = comprar(app, {"1": 2})
    assert segundo == primero
    assert total_pedidos(app) == 1 and stock(app, COLONOS) == 10


def test_confirmar_otra_vez_con_la_cesta_ya_vacia_devuelve_el_mismo_pedido(app):
    """US-17-AC-07: la interfaz vacía la cesta tras comprar, y repetir no da error."""
    primero = comprar(app, {"1": 2})
    assert comprar(app, {}) == primero and stock(app, COLONOS) == 10


def test_otro_checkout_crea_otro_pedido(app):
    comprar(app, {"1": 1}, codigo="a")
    pedido = comprar(app, {"1": 1}, codigo="b")
    assert pedido["numero"] == "PED-00002" and total_pedidos(app) == 2 and stock(app, COLONOS) == 10
