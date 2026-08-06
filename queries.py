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
import calendar
import streamlit as st
import pandas as pd
from datetime import date
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
        # IMPORTANTE: se incluye codigo_ref (índice 5) porque
        # 1_Recepcion_Vehiculos.py lo usa (p[5]) para la búsqueda por código
        # de barras, e iva_tipo (índice 6) porque los repuestos tomados del
        # almacén heredan directamente el tipo de IVA configurado en el
        # producto. Si se quita alguna, esas partes vuelven a romper.
        prods = conn.execute(
            text("SELECT id, nombre_producto, stock_actual, costo_compra, precio_venta, codigo_ref, iva_tipo "
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


@st.cache_data(ttl=30)
def obtener_mecanicos_activos(uid):
    """Solo mecánicos con estado='Activo'. Compartida entre Nómina y
    Control de Aceites/Flotas (ambas necesitan la misma lista para asignar
    técnicos, filtrando a quienes siguen trabajando en el taller)."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid AND estado = 'Activo' ORDER BY nombre ASC")
        return conn.execute(query, {"uid": uid}).fetchall()


@st.cache_data(ttl=60)
def obtener_empresas_directorio(uid):
    """Vista completa (con NIT, teléfono, email) para el Directorio/CRM.
    Distinta de obtener_catalogos, que solo trae id+nombre para dropdowns."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("SELECT id, razon_social, nit, telefono, email, "
                 "COALESCE(tipo_documento, 'NIT') as tipo_documento FROM Empresas_Clientes "
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


@st.cache_data(ttl=60)
def obtener_categorias_gasto(uid):
    """Categorías de gasto predefinidas para el usuario."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text("SELECT id, nombre, tipo FROM Categorias_Gasto WHERE usuario_id = :uid ORDER BY nombre ASC")
        return conn.execute(query, {"uid": uid}).fetchall()


@st.cache_data(ttl=30)
def obtener_gastos_filtrado(uid, fecha_inicio, fecha_fin, categoria_id=None):
    """Gastos en un rango de fechas, opcionalmente filtrados por categoría."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        condicion = ""
        params = {"uid": uid, "f_ini": fecha_inicio.strftime('%Y-%m-%d'), "f_fin": fecha_fin.strftime('%Y-%m-%d')}
        if categoria_id:
            condicion = "AND categoria_id = :cat_id"
            params["cat_id"] = categoria_id
        
        query = text(f"""
            SELECT g.id, g.categoria_id, c.nombre as categoria, g.descripcion, g.monto, g.fecha, g.tipo
            FROM Gastos g
            JOIN Categorias_Gasto c ON g.categoria_id = c.id
            WHERE g.usuario_id = :uid AND g.fecha >= :f_ini AND g.fecha <= :f_fin {condicion}
            ORDER BY g.fecha DESC
        """)
        return pd.read_sql_query(query, con=conn, params=params)


@st.cache_data(ttl=60)
def obtener_metricas_financieras(uid, año, mes):
    """Ingresos (órdenes facturadas) y gastos totales en un mes específico.
    Usa un rango de fechas en vez de EXTRACT(): EXTRACT(YEAR/MONTH FROM ...)
    es sintaxis exclusiva de Postgres y rompe contra el fallback local a
    SQLite (mismo ajuste aplicado en MyInv/obtener_metricas_mes)."""
    engine = obtener_conexion()
    f_ini = date(año, mes, 1).strftime('%Y-%m-%d')
    f_fin = date(año, mes, calendar.monthrange(año, mes)[1]).strftime('%Y-%m-%d')
    with engine.connect() as conn:
        ingresos = conn.execute(text("""
            SELECT COALESCE(SUM(d.precio_venta), 0)
            FROM Hojas_Trabajo h
            JOIN Detalles_Orden d ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND h.estado = 'Facturado'
            AND DATE(h.fecha_ingreso) >= :f_ini AND DATE(h.fecha_ingreso) <= :f_fin
        """), {"uid": uid, "f_ini": f_ini, "f_fin": f_fin}).scalar()

        gastos = conn.execute(text("""
            SELECT COALESCE(SUM(monto), 0)
            FROM Gastos
            WHERE usuario_id = :uid
            AND fecha >= :f_ini AND fecha <= :f_fin
        """), {"uid": uid, "f_ini": f_ini, "f_fin": f_fin}).scalar()

    return (float(ingresos) if ingresos else 0.0, float(gastos) if gastos else 0.0)


@st.cache_data(ttl=30)
def obtener_gastos_por_categoria(uid, fecha_inicio, fecha_fin):
    """Suma de gastos agrupada por categoría (para gráficos)."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text("""
            SELECT c.nombre, SUM(g.monto) as total
            FROM Gastos g
            JOIN Categorias_Gasto c ON g.categoria_id = c.id
            WHERE g.usuario_id = :uid AND g.fecha >= :f_ini AND g.fecha <= :f_fin
            GROUP BY c.id, c.nombre
            ORDER BY total DESC
        """)
        return pd.read_sql_query(query, con=conn, params={"uid": uid, "f_ini": fecha_inicio.strftime('%Y-%m-%d'), "f_fin": fecha_fin.strftime('%Y-%m-%d')})


def invalidar_cache_gastos():
    """Llamar después de crear, editar o eliminar un gasto."""
    obtener_categorias_gasto.clear()
    obtener_gastos_filtrado.clear()
    obtener_metricas_financieras.clear()
    obtener_gastos_por_categoria.clear()


def invalidar_cache_directorio():
    """
    Llamar tras crear, editar o eliminar una Empresa_Cliente o un Mecánico.
    Limpia las tablas del propio Directorio, obtener_catalogos (dropdowns en
    Recepción, Expediente y Nómina) y obtener_mecanicos_activos (Nómina y
    Aceites/Flotas), ya que editar el estado Activo/Inactivo de un mecánico
    aquí afecta directamente a esa lista.
    """
    obtener_catalogos.clear()
    obtener_empresas_directorio.clear()
    obtener_mecanicos_directorio.clear()
    obtener_mecanicos_activos.clear()


def invalidar_cache_ordenes():
    """
    Llamar después de CUALQUIER escritura que cambie estado, precios o ítems
    de una orden (Hojas_Trabajo / Detalles_Orden). Cubre Dashboard, Tablero,
    la lista de pendientes por cotizar y los ingresos del mes (una orden que
    pasa a o desde 'Facturado', o cuyos precios cambian, altera el total
    facturado del mes).
    """
    obtener_metricas_dashboard.clear()
    obtener_ordenes_con_items_pendientes.clear()
    obtener_vehiculos.clear()
    obtener_metricas_financieras.clear()


def invalidar_cache_inventario():
    """Llamar además de invalidar_cache_ordenes() cuando la escritura también
    descuenta o modifica stock de Inventario."""
    obtener_inventario_activo.clear()


@st.cache_data(ttl=120)
def obtener_config_taller(uid):
    """Config del taller (tabla Usuarios): datos de contacto, logo e IVA.
    Centraliza una consulta que antes se repetía sin caché en Recepción,
    Expediente, Inventario y Configuración del Taller — cada una la
    disparaba de nuevo en cada rerun de página."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT nombre_taller, nombre_dueno, email, logo_path,
                       iva_activo, iva_incluido,
                       iva_tipo_default_mano_obra, iva_tipo_default_repuestos
                FROM Usuarios WHERE id = :uid
            """),
            {"uid": uid}
        ).fetchone()
    return tuple(row) if row else None


def invalidar_cache_config_taller():
    """Llamar tras guardar el logo o la configuración de IVA en Configuración del Taller."""
    obtener_config_taller.clear()


@st.cache_data(ttl=30)
def obtener_operarios_patio(uid):
    """Operarios de patio del taller, para Configuración del Taller."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return conn.execute(
            text("""
                SELECT id, nombre_operario, usuario_login, activo
                FROM Operarios_Patio
                WHERE usuario_id = :uid
                ORDER BY nombre_operario ASC
            """),
            {"uid": uid}
        ).fetchall()


def invalidar_cache_operarios():
    """Llamar tras crear, activar/desactivar o resetear la clave de un operario de patio."""
    obtener_operarios_patio.clear()


# ==========================================
# FACTURACIÓN ELECTRÓNICA (ALEGRA)
# ==========================================
def obtener_credenciales_alegra(uid):
    """Credenciales de Alegra configuradas por este taller (o None si no ha configurado nada)."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT alegra_email, alegra_token
            FROM Usuarios WHERE id = :uid
        """), {"uid": uid}).fetchone()


def guardar_credenciales_alegra(uid, email, token):
    """Guarda (o actualiza) las credenciales de Alegra de este taller."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Usuarios SET alegra_email = :email, alegra_token = :token WHERE id = :uid
        """), {"email": email, "token": token, "uid": uid})


def eliminar_credenciales_alegra(uid):
    """Desconecta la cuenta de Alegra de este taller."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Usuarios SET alegra_email = NULL, alegra_token = NULL WHERE id = :uid
        """), {"uid": uid})


@st.cache_data(ttl=60)
def tiene_fe_habilitada(uid):
    """Indica si el administrador habilitó la Facturación Electrónica para este
    taller. Controla el acceso a toda la funcionalidad de Alegra/DIAN."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        valor = conn.execute(
            text("SELECT fe_habilitada FROM Usuarios WHERE id = :uid"), {"uid": uid}
        ).scalar()
    return bool(valor)


def establecer_fe_habilitada(uid, habilitada):
    """Habilita o deshabilita la Facturación Electrónica para un taller (solo admin)."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE Usuarios SET fe_habilitada = :val WHERE id = :uid"),
            {"val": bool(habilitada), "uid": uid}
        )
    tiene_fe_habilitada.clear()


def obtener_datos_facturacion_empresa(uid, empresa_id):
    """Datos de la Empresa_Cliente necesarios para facturar electrónicamente (sin caché, siempre al día)."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT id, razon_social, nit, tipo_documento, email, alegra_contact_id
            FROM Empresas_Clientes
            WHERE usuario_id = :uid AND id = :eid
        """), {"uid": uid, "eid": empresa_id}).fetchone()


def guardar_alegra_contact_id(empresa_id, alegra_contact_id):
    """Guarda el id de contacto en Alegra la primera vez que se crea, para reutilizarlo después."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Empresas_Clientes SET alegra_contact_id = :alegra_id WHERE id = :eid
        """), {"alegra_id": alegra_contact_id, "eid": empresa_id})
    invalidar_cache_directorio()


def obtener_orden_para_facturar(uid, hoja_id):
    """Datos base de una orden necesarios para emitirla como factura electrónica."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT id, empresa_id, tipo_pago, fecha_vencimiento_credito,
                   factura_alegra_id, factura_estado, factura_cufe,
                   factura_pdf_url, factura_xml_url,
                   nota_credito_alegra_id, nota_credito_pdf_url, nota_credito_xml_url
            FROM Hojas_Trabajo
            WHERE id = :hid AND usuario_id = :uid
        """), {"hid": hoja_id, "uid": uid}).fetchone()


def obtener_items_orden(hoja_id):
    """Renglones de una orden (mano de obra/repuestos) para armar la factura electrónica."""
    engine = obtener_conexion()
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT id, tipo_item, descripcion, precio_venta, iva_tipo
            FROM Detalles_Orden WHERE hoja_id = :hid
        """), {"hid": hoja_id}).fetchall()


def guardar_resultado_factura(hoja_id, alegra_id=None, cufe=None, pdf_url=None, xml_url=None,
                               estado="emitida", prefijo=None, numero=None,
                               tipo_pago=None, fecha_vencimiento=None):
    """Guarda el resultado de crear (o intentar emitir) la factura electrónica de una orden."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Hojas_Trabajo
            SET factura_alegra_id = :alegra_id, factura_cufe = :cufe,
                factura_pdf_url = :pdf_url, factura_xml_url = :xml_url, factura_estado = :estado,
                factura_prefijo = :prefijo, factura_numero = :numero,
                tipo_pago = COALESCE(:tipo_pago, tipo_pago),
                fecha_vencimiento_credito = COALESCE(:fecha_vencimiento, fecha_vencimiento_credito)
            WHERE id = :hid
        """), {
            "alegra_id": alegra_id, "cufe": cufe, "pdf_url": pdf_url, "xml_url": xml_url,
            "estado": estado, "prefijo": prefijo, "numero": numero, "hid": hoja_id,
            "tipo_pago": tipo_pago, "fecha_vencimiento": fecha_vencimiento,
        })
    invalidar_cache_ordenes()


def actualizar_datos_factura(hoja_id, cufe=None, pdf_url=None, xml_url=None, prefijo=None, numero=None):
    """Completa CUFE/PDF/XML/prefijo/número de una factura ya emitida sin pisar lo que ya
    estaba guardado. Se usa al refrescar el enlace de una factura antigua."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Hojas_Trabajo
            SET factura_cufe = COALESCE(:cufe, factura_cufe),
                factura_pdf_url = COALESCE(:pdf_url, factura_pdf_url),
                factura_xml_url = COALESCE(:xml_url, factura_xml_url),
                factura_prefijo = COALESCE(:prefijo, factura_prefijo),
                factura_numero = COALESCE(:numero, factura_numero)
            WHERE id = :hid
        """), {
            "cufe": cufe, "pdf_url": pdf_url, "xml_url": xml_url,
            "prefijo": prefijo, "numero": numero, "hid": hoja_id
        })
    invalidar_cache_ordenes()


def guardar_nota_credito(hoja_id, nota_credito_alegra_id, pdf_url=None, xml_url=None, prefijo=None, numero=None):
    """Guarda el id, número (prefijo+consecutivo) y PDF/XML de la nota crédito
    emitida en Alegra para una orden anulada."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Hojas_Trabajo SET nota_credito_alegra_id = :ncid, nota_credito_pdf_url = :pdf_url,
                   nota_credito_xml_url = :xml_url, nota_credito_prefijo = :prefijo,
                   nota_credito_numero = :numero
            WHERE id = :hid
        """), {
            "ncid": nota_credito_alegra_id, "pdf_url": pdf_url, "xml_url": xml_url,
            "prefijo": prefijo, "numero": numero, "hid": hoja_id
        })
    invalidar_cache_ordenes()


def actualizar_pdf_nota_credito(hoja_id, pdf_url, xml_url=None, prefijo=None, numero=None):
    """Completa PDF/XML/número de una nota crédito ya emitida, cuando no llegaron
    en la respuesta de creación, o al refrescar un enlace antiguo."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE Hojas_Trabajo
            SET nota_credito_pdf_url = COALESCE(:pdf_url, nota_credito_pdf_url),
                nota_credito_xml_url = COALESCE(:xml_url, nota_credito_xml_url),
                nota_credito_prefijo = COALESCE(:prefijo, nota_credito_prefijo),
                nota_credito_numero = COALESCE(:numero, nota_credito_numero)
            WHERE id = :hid
        """), {
            "pdf_url": pdf_url, "xml_url": xml_url,
            "prefijo": prefijo, "numero": numero, "hid": hoja_id
        })
    invalidar_cache_ordenes()


def marcar_orden_facturada(hoja_id):
    """Pasa la orden a estado operativo 'Facturado' cuando su factura
    electrónica queda emitida ante la DIAN (evita el paso manual de cambiar
    el estado aparte)."""
    engine = obtener_conexion()
    with engine.begin() as conn:
        conn.execute(text("UPDATE Hojas_Trabajo SET estado = 'Facturado' WHERE id = :hid"), {"hid": hoja_id})
    invalidar_cache_ordenes()
