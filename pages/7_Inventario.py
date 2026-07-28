import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion, init_db
from queries import invalidar_cache_inventario

st.set_page_config(page_title="Inventario y Almacén", layout="wide")

init_db()

st.markdown("""
    <style>
    header::after {
        content: "";
        position: fixed !important;
        top: 0 !important;
        right: 0 !important;
        width: 350px !important;
        height: 60px !important;
        background-color: var(--background-color) !important;
        z-index: 9999999 !important;
        pointer-events: all !important;
    }
    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out; }
    div[data-testid="stVerticalBlock"] > div { animation: fade-in-up 0.5s ease-out; }
    </style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------------
# AUTENTICACIÓN: mismo namespace st.session_state.auth definido en app.py
# --------------------------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

LIMITE_FILAS = 100

# ==========================================
# MÉTRICAS: agregadas en SQL, NO dependen de traer todo el inventario a pandas.
# Así siguen siendo correctas (sobre el catálogo completo) aunque la tabla
# de abajo esté filtrada o limitada a 100 filas.
# ==========================================
@st.cache_data(ttl=60)
def obtener_metricas_inventario(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        query = text('''
            SELECT
                COALESCE(SUM(stock_actual * costo_compra), 0) AS val_costo,
                COALESCE(SUM(stock_actual * precio_venta), 0) AS val_venta,
                COALESCE(SUM(CASE WHEN stock_actual > 0 AND stock_actual <= stock_minimo THEN 1 ELSE 0 END), 0) AS por_agotarse,
                COALESCE(SUM(CASE WHEN stock_actual <= 0 THEN 1 ELSE 0 END), 0) AS agotados,
                COUNT(*) AS total_productos
            FROM Inventario
            WHERE usuario_id = :uid
        ''')
        row = conn.execute(query, {"uid": uid}).fetchone()
    return row.val_costo, row.val_venta, row.por_agotarse, row.agotados, row.total_productos


def obtener_inventario_filtrado(uid, busqueda, limite):
    """
    Sin @st.cache_data a propósito: esta tabla es editable en vivo y el
    usuario espera ver el resultado exacto de su búsqueda al instante,
    no una copia cacheada. El límite en SQL es lo que evita traer miles
    de filas de golpe, no el cache.
    """
    engine = obtener_conexion()
    params = {"uid": uid, "limit": limite}
    condicion_busqueda = ""
    if busqueda:
        condicion_busqueda = "AND (nombre_producto ILIKE :busq OR codigo_ref ILIKE :busq)" \
            if "postgres" in str(engine.url) else \
            "AND (nombre_producto LIKE :busq OR codigo_ref LIKE :busq)"
        params["busq"] = f"%{busqueda}%"

    with engine.connect() as conn:
        query = text(f'''
            SELECT id, nombre_producto, codigo_ref, stock_actual, stock_minimo, costo_compra, precio_venta 
            FROM Inventario 
            WHERE usuario_id = :uid {condicion_busqueda}
            ORDER BY nombre_producto ASC
            LIMIT :limit
        ''')
        return pd.read_sql_query(query, con=conn, params=params)


st.title("Inventario de Almacén")
st.markdown(f"Control de stock de repuestos e insumos para: **{nombre_taller}**")
st.markdown("---")

tab_stock, tab_nuevo = st.tabs(["Stock Actual y Alertas", "Agregar Producto al Almacén"])

# ==========================================
# TAB 1: VER EXISTENCIAS Y EDITAR
# ==========================================
with tab_stock:
    val_costo, val_venta, por_agotarse, agotados, total_productos = obtener_metricas_inventario(user_id)

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Inversión en Stock (Costo)", formato_cop(val_costo))
    col_m2.metric("Valor Comercial (Venta)", formato_cop(val_venta))
    col_m3.metric("Por Agotarse (Alerta)", por_agotarse)
    col_m4.metric("Agotados (Sin Stock)", agotados)

    st.markdown("---")

    if total_productos == 0:
        st.info("Aún no tienes repuestos o insumos registrados en el almacén de tu taller.")
    else:
        st.subheader("Gestión de Productos en Stock")
        busqueda = st.text_input(
            "Buscar por nombre o código de referencia",
            placeholder="Ej: filtro de aceite, ref. 4521...",
            help="Escribe para filtrar. Sin búsqueda se muestran los primeros "
                 f"{LIMITE_FILAS} productos ordenados alfabéticamente."
        )

        df_inv = obtener_inventario_filtrado(user_id, busqueda.strip(), LIMITE_FILAS)

        if df_inv.empty:
            st.warning("No se encontraron productos que coincidan con la búsqueda.")
        else:
            if len(df_inv) == LIMITE_FILAS and total_productos > LIMITE_FILAS:
                st.caption(
                    f"⚠️ Mostrando los primeros {LIMITE_FILAS} de {total_productos} productos. "
                    "Usa el buscador para acotar y editar un producto específico."
                )

            st.caption("Puedes modificar los valores directamente en la tabla y hacer clic en guardar.")

            df_editado = st.data_editor(
                df_inv,
                hide_index=True,
                use_container_width=True,
                disabled=["id"],
                column_config={
                    "id": None,
                    "nombre_producto": "Producto / Repuesto",
                    "codigo_ref": "Código / Ref",
                    "stock_actual": st.column_config.NumberColumn("Cantidad en Stock", min_value=0, step=1),
                    "stock_minimo": st.column_config.NumberColumn("Stock Mínimo (Alerta)", min_value=1, step=1),
                    "costo_compra": st.column_config.NumberColumn("Costo Compra ($)", format="$%d"),
                    "precio_venta": st.column_config.NumberColumn("Precio Venta ($)", format="$%d")
                },
                key=f"editor_inv_{busqueda}"
            )

            if st.button("Guardar Cambios de Inventario", type="primary"):
                try:
                    with engine.begin() as conn_upd:
                        for idx, row in df_editado.iterrows():
                            conn_upd.execute(
                                text("""
                                    UPDATE Inventario 
                                    SET nombre_producto = :nom, codigo_ref = :ref, stock_actual = :st_act,
                                        stock_minimo = :st_min, costo_compra = :costo, precio_venta = :pvp
                                    WHERE id = :id AND usuario_id = :uid
                                """),
                                {
                                    "nom": row['nombre_producto'],
                                    "ref": row['codigo_ref'],
                                    "st_act": int(row['stock_actual']),
                                    "st_min": int(row['stock_minimo']),
                                    "costo": float(row['costo_compra']),
                                    "pvp": float(row['precio_venta']),
                                    "id": int(row['id']),
                                    "uid": user_id
                                }
                            )
                    # Invalida las métricas de esta página y el inventario
                    # compartido que usan Recepción, Expediente y Aceites/Flotas.
                    obtener_metricas_inventario.clear()
                    invalidar_cache_inventario()
                    st.success("Inventario actualizado y sincronizado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al actualizar inventario: {e}")

# ==========================================
# TAB 2: REGISTRAR NUEVO PRODUCTO
# ==========================================
with tab_nuevo:
    st.subheader("Registrar Nuevo Producto o Insumo")
    with st.form("form_nuevo_producto", clear_on_submit=True):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            nom_p = st.text_input("Nombre del Repuesto / Insumo")
            ref_p = st.text_input("Código o Referencia (Opcional)")
            stk_p = st.number_input("Cantidad Inicial en Stock", min_value=1, value=5, step=1)
        with col_p2:
            stk_min_p = st.number_input("Stock Mínimo (Alerta de Reabastecimiento)", min_value=1, value=2, step=1)
            costo_p = st.number_input("Costo de Compra ($)", min_value=0.0, step=1000.0)
            venta_p = st.number_input("Precio de Venta al Cliente ($)", min_value=0.0, step=1000.0)

        if st.form_submit_button("Guardar en Inventario", type="primary"):
            if nom_p and venta_p > 0:
                try:
                    with engine.begin() as conn_ins:
                        conn_ins.execute(
                            text("""
                                INSERT INTO Inventario (usuario_id, nombre_producto, codigo_ref, stock_actual, stock_minimo, costo_compra, precio_venta)
                                VALUES (:uid, :nom, :ref, :stk, :stk_min, :costo, :pvp)
                            """),
                            {
                                "uid": user_id,
                                "nom": nom_p,
                                "ref": ref_p,
                                "stk": int(stk_p),
                                "stk_min": int(stk_min_p),
                                "costo": float(costo_p),
                                "pvp": float(venta_p)
                            }
                        )
                    obtener_metricas_inventario.clear()
                    invalidar_cache_inventario()
                    st.success(f"Producto '{nom_p}' registrado con éxito en el almacén.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar producto: {e}")
            else:
                st.warning("Escribe el nombre del producto y asigna un precio de venta válido.")
