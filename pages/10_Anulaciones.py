import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from queries import obtener_catalogos, obtener_notas_credito_periodo
import alegra_utils

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

# Bloqueo de rol: los operarios de Patio solo tienen acceso a Recepción.
if st.session_state.auth.get("rol") == "patio":
    st.warning("🔒 Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("Anulaciones")
st.markdown(f"Notas crédito (facturas anuladas) para: **{nombre_taller}**")
st.markdown("---")

# ==========================================
# FILTROS
# ==========================================
with st.expander("Filtros de Búsqueda", expanded=True):
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        hoy = datetime.today()
        hace_90_dias = hoy - timedelta(days=90)
        fechas_filtro = st.date_input("Rango de fechas (fecha de la nota crédito)", [hace_90_dias, hoy])
    with col_f2:
        filtro_orden = st.text_input("N° de Orden (Opcional)").strip()
        filtro_factura = st.text_input("N° de Factura (Opcional)").strip()
    with col_f3:
        filtro_placa = st.text_input("Placa del Vehículo (Opcional)").upper().strip()
        empresas, _ = obtener_catalogos(user_id)
        dict_empresas_filtro = {e[1]: e[0] for e in empresas}
        opciones_empresas_filtro = ["-- Todos los clientes --"] + list(dict_empresas_filtro.keys())
        filtro_empresa_sel = st.selectbox("Cliente (Opcional)", options=opciones_empresas_filtro)

if len(fechas_filtro) == 2:
    fecha_inicio, fecha_fin = fechas_filtro
    # nota_credito_fecha es TIMESTAMP (no solo fecha): se extiende el fin un
    # día para no perder las notas crédito emitidas el mismo día final.
    fecha_fin_extendida = fecha_fin + timedelta(days=1)

    df_nc = obtener_notas_credito_periodo(user_id, fecha_inicio, fecha_fin_extendida)

    if not df_nc.empty:
        if filtro_orden:
            df_nc = df_nc[df_nc['hoja_id'].astype(str).str.contains(filtro_orden, case=False, na=False)]
        if filtro_factura:
            df_nc['numero_factura_texto'] = (
                df_nc['factura_prefijo'].fillna('').astype(str) + df_nc['factura_numero'].fillna('').astype(str)
            )
            df_nc = df_nc[df_nc['numero_factura_texto'].str.contains(filtro_factura, case=False, na=False)]
        if filtro_placa:
            df_nc = df_nc[df_nc['placa'].str.contains(filtro_placa, case=False, na=False)]
        if filtro_empresa_sel != "-- Todos los clientes --":
            df_nc = df_nc[df_nc['cliente'] == filtro_empresa_sel]

    if df_nc.empty:
        st.info("No se encontraron notas crédito que coincidan con los filtros seleccionados.")
    else:
        st.subheader(f"Notas Crédito Encontradas: {len(df_nc)}")

        df_mostrar = df_nc.copy()
        df_mostrar['N° Factura'] = (
            df_mostrar['factura_prefijo'].fillna('').astype(str) + df_mostrar['factura_numero'].fillna('').astype(str)
        )
        df_mostrar['N° Nota Crédito'] = (
            df_mostrar['nota_credito_prefijo'].fillna('').astype(str) + df_mostrar['nota_credito_numero'].fillna('').astype(str)
        )

        df_mostrar = df_mostrar[[
            'hoja_id', 'nota_credito_fecha', 'placa', 'cliente', 'nit',
            'N° Factura', 'N° Nota Crédito', 'total'
        ]].rename(columns={
            'hoja_id': 'N° Orden', 'nota_credito_fecha': 'Fecha NC', 'placa': 'Placa',
            'cliente': 'Cliente', 'nit': 'NIT', 'total': 'Total Anulado',
        })

        st.dataframe(
            df_mostrar,
            width='stretch', hide_index=True,
            column_config={
                "Total Anulado": st.column_config.NumberColumn(format="$%,d"),
            }
        )

        st.caption(f"Total anulado en el período filtrado: {formato_cop(df_mostrar['Total Anulado'].sum())}")

        st.markdown("---")
        st.markdown("**Descargar PDF/XML de una nota crédito específica:**")
        dict_nc = {
            f"Orden #{r['hoja_id']} — {r['cliente']} (Placa {r['placa']}) — {formato_cop(r['total'])}": i
            for i, r in df_nc.iterrows()
        }
        nc_sel_str = st.selectbox("Selecciona una nota crédito", options=list(dict_nc.keys()))
        fila_nc = df_nc.loc[dict_nc[nc_sel_str]]

        col_dl1, col_dl2 = st.columns(2)
        alegra_utils.mostrar_documento(
            col_dl1, "Descargar PDF", fila_nc['nota_credito_pdf_url'],
            f"NotaCredito_Orden_{fila_nc['hoja_id']}.pdf", "application/pdf"
        )
        alegra_utils.mostrar_documento(
            col_dl2, "Descargar XML", fila_nc['nota_credito_xml_url'],
            f"NotaCredito_Orden_{fila_nc['hoja_id']}.xml", "application/xml"
        )
else:
    st.warning("Por favor selecciona un rango de fechas válido.")
