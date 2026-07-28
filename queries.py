"""
queries.py — Punto único de acceso a datos cacheados para MyTaller.

Por qué existe este archivo:
Antes, cada página (Dashboard, Recepción, Tablero, Expediente...) definía
sus propias funciones @st.cache_data, aunque consultaran las mismas tablas.
Eso generaba dos problemas:
  1. Cachés duplicados para los mismos datos (una copia por archivo).
  2. Imposible invalidar selectivamente: si en Expediente cambiabas el precio
     de un ítem, no había forma de avisarle al caché del Tablero o del
     Dashboard (que viven en otro archivo) que sus datos ya quedaron viejos.

Con todas las consultas centralizadas aquí, cualquier página puede importar
la función exacta que necesita invalidar tras una escritura, por ejemplo:
    from queries import obtener_vehiculos
    ...
    obtener_vehiculos.clear()
"""
import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion


@st.cache_data(ttl=30, show_spinner=False)
def obtener_metricas_dashboard(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text('''
            SELECT
                (SELECT COALESCE(SUM(d.precio_venta), 0)
                 FROM Detalles_Orden d
                 JOIN Hojas_Trabajo h ON d.hoja_id = h.id
                 WHERE h.usuario_id = :uid AND h.estado != 'Facturado') AS total_activos,
                (SELECT COUNT(*) FROM Hojas_Trabajo
                 WHERE usuario_id = :uid AND estado = 'Cotizar') AS total_cotizar,
                (SELECT COUNT(*) FROM Hojas_Trabajo
                 WHERE usuario_id = :uid AND estado != 'Facturado') AS total_ordenes_activas,
                (SELECT COUNT(*) FROM Empresas_Clientes
                 WHERE usuario_id = :uid) AS total_empresas
        ''')
        row = conn.execute(query, {"uid": uid}).fetchone()
    return row.total_activos, row.total_cotizar, row.total_ordenes_activas, row.total_empresas


@st.cache_data(ttl=300)
def obtener_catalogos(uid):
    """Devuelve (empresas, mecanicos) como listas de tuplas (id, nombre)."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        empresas_db = conn.execute(
            text("SELECT id, razon_social FROM Empresas_Clientes WHERE usuario_id = :uid ORDER BY razon_social ASC"),
            {"uid": uid}
        ).fetchall()
        mecanicos_db = conn.execute(
            text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid ORDER BY nombre ASC"),
            {"uid": uid}
        ).fetchall()
    return [tuple(e) for e in empresas_db], [tuple(m) for m in mecanicos_db]


@st.cache_data(ttl=60)
def obtener_inventario_activo(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        prods = conn.execute(
            text("SELECT id, nombre_producto, stock_actual, costo_compra, precio_venta "
                 "FROM Inventario WHERE usuario_id = :uid AND stock_actual > 0 ORDER BY nombre_producto ASC"),
            {"uid": uid}
        ).fetchall()
    return [tuple(p) for p in prods]


@st.cache_data(ttl=15)
def obtener_ordenes_con_items_pendientes(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text('''
            SELECT DISTINCT h.id, h.placa, e.razon_social
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            JOIN Detalles_Orden d ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND (d.precio_venta = 0 OR d.precio_venta IS NULL)
            ORDER BY h.id DESC
        ''')
        return conn.execute(query, {"uid": uid}).fetchall()


@st.cache_data(ttl=15)
def obtener_vehiculos(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text('''
            SELECT h.id, h.placa, e.razon_social, h.estado,
                   SUM(CASE WHEN d.precio_venta = 0 OR d.precio_venta IS NULL THEN 1 ELSE 0 END) as items_sin_precio
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            LEFT JOIN Detalles_Orden d ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND h.estado != 'Facturado'
            GROUP BY h.id, h.placa, e.razon_social, h.estado
        ''')
        return conn.execute(query, {"uid": uid}).fetchall()


@st.cache_data(ttl=60)
def obtener_empresas_directorio(uid):
    """Vista completa (con NIT, teléfono, email) para el Directorio/CRM.
    Distinta de obtener_catalogos, que solo trae id+nombre para dropdowns."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("SELECT id, razon_social, nit, telefono, email FROM Empresas_Clientes "
                 "WHERE usuario_id = :uid ORDER BY razon_social ASC"),
            con=conn, params={"uid": uid}
        )


@st.cache_data(ttl=60)
def obtener_mecanicos_directorio(uid):
    """Vista completa (con documento y estado) para el Directorio/CRM."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("SELECT id, nombre, documento, estado FROM Mecanicos "
                 "WHERE usuario_id = :uid ORDER BY nombre ASC"),
            con=conn, params={"uid": uid}
        )


def invalidar_cache_directorio():
    """
    Llamar tras crear, editar o eliminar una Empresa_Cliente o un Mecánico.
    Limpia tanto las tablas del propio Directorio como obtener_catalogos
    (usada en los dropdowns de Recepción, Expediente y Nómina), para que
    una empresa o mecánico nuevo aparezca de inmediato en toda la app.
    """
    obtener_catalogos.clear()
    obtener_empresas_directorio.clear()
    obtener_mecanicos_directorio.clear()


def invalidar_cache_ordenes():
    """
    Llamar después de CUALQUIER escritura que cambie estado, precios o ítems
    de una orden (Hojas_Trabajo / Detalles_Orden). Cubre Dashboard, Tablero
    y la lista de pendientes por cotizar.
    """
    obtener_metricas_dashboard.clear()
    obtener_ordenes_con_items_pendientes.clear()
    obtener_vehiculos.clear()


def invalidar_cache_inventario():
    """Llamar además de invalidar_cache_ordenes() cuando la escritura también
    descuenta o modifica stock de Inventario."""
    obtener_inventario_activo.clear()
