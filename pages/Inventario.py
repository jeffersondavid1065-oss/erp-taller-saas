import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion, init_db

st.set_page_config(page_title="Inventario y Almacén", layout="wide")

# Asegura que las tablas existan
init_db()

# ESTILOS CSS CON MÁSCARA DERECHA ADAPTABLE Y ANIMACIÓN
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

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("Inventario de Almacén")
st.markdown(f"Control de stock de repuestos e insumos para: **{st.session_state.nombre_taller}**")
st.markdown("---")

tab_stock, tab_nuevo = st.tabs(["Stock Actual y Alertas", "Agregar Producto al Almacén"])

# ==========================================
# TAB 1: VER EXISTENCIAS Y EDITAR
# ==========================================
with tab_stock:
    with engine.connect() as conn:
        df_inv = pd.read_sql_query(
            text("""
                SELECT id, nombre_producto, codigo_ref, stock_actual, stock_minimo, costo_compra, precio_venta 
                FROM Inventario 
                WHERE usuario_id = :uid 
                ORDER BY nombre_producto ASC
            """),
            con=conn,
            params={"uid": user_id}
        )

    if not df_inv.empty:
        # Métricas de la parte superior
        val_costo = (df_inv['stock_actual'] * df_inv['costo_compra']).sum()
        val_venta = (df_inv['stock_actual'] * df_inv['precio_venta']).sum()
        por_agotarse = len(df_inv[(df_inv['stock_actual'] > 0) & (df_inv['stock_actual'] <= df_inv['stock_minimo'])])
        agotados = len(df_inv[df_inv['stock_actual'] <= 0])

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Inversión en Stock (Costo)", formato_cop(val_costo))
        col_m2.metric("Valor Comercial (Venta)", formato_cop(val_venta))
        col_m3.metric("Por Agotarse (Alerta)", por_agotarse)
        col_m4.metric("Agotados (Sin Stock)", agotados)

        st.markdown("---")
        st.subheader("Gestión de Productos en Stock")
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
            }
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
                st.success("Inventario actualizado y sincronizado.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al actualizar inventario: {e}")
    else:
        st.info("Aún no tienes repuestos o insumos registrados en el almacén de tu taller.")

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
                    st.success(f"Producto '{nom_p}' registrado con éxito en el almacén.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar producto: {e}")
            else:
                st.warning("Escribe el nombre del producto y asigna un precio de venta válido.")
