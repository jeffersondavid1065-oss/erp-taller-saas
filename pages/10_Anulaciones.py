import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion
from queries import obtener_catalogos, obtener_notas_credito_periodo, invalidar_cache_ordenes
import factus_utils

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
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out !important; }
    div[data-testid="stVerticalBlock"] > div { animation: fade-in-up 0.5s ease-out !important; }
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

if st.session_state.get("debug_anular_result"):
    st.info(f"DEBUG (temporal): {st.session_state.pop('debug_anular_result')}")

st.title("Anulaciones")
st.markdown(f"Notas crédito (facturas anuladas) para: **{nombre_taller}**")
st.markdown("---")

# ==========================================
# ANULAR UNA FACTURA
# ==========================================
st.subheader("Anular una Factura")
st.caption(
    "Usa esto solo si el trabajo se anuló o devolvió después de facturado. "
    "Genera una nota crédito ante la DIAN que anula la factura electrónica de esa orden."
)

orden_anular_busqueda = st.text_input("Número de Orden a anular", key="orden_anular_valor").strip()

if orden_anular_busqueda:
    if not orden_anular_busqueda.isdigit():
        st.warning("Ingresa solo el número de la orden (sin letras ni símbolos).")
    else:
        numero_orden_anular = int(orden_anular_busqueda)
        engine = obtener_conexion()
        with engine.connect() as conn:
            orden_anular = conn.execute(text('''
                SELECT h.id, h.placa, e.razon_social, h.factura_estado,
                       h.nota_credito_reference_code, h.factura_prefijo, h.factura_numero, h.tipo_pago
                FROM Hojas_Trabajo h
                JOIN Empresas_Clientes e ON h.empresa_id = e.id
                WHERE h.numero_orden = :nro AND h.usuario_id = :uid
            '''), {"nro": numero_orden_anular, "uid": user_id}).fetchone()

        if not orden_anular:
            st.warning(f"No se encontró ninguna orden con el número #{numero_orden_anular} en tu taller.")
        else:
            (hoja_id_anular, placa_anular, cliente_anular, factura_estado_anular,
             nota_credito_anular, prefijo_anular, numero_anular, tipo_pago_anular) = orden_anular
            numero_factura_anular = f"{prefijo_anular or ''}{numero_anular or ''}"

            st.markdown(f"**Orden #{numero_orden_anular}** — Placa {placa_anular} — {cliente_anular}")

            if factura_estado_anular != "emitida":
                st.info("Esta orden no tiene una factura electrónica emitida ante la DIAN para anular.")
            elif nota_credito_anular:
                st.info("Esta factura ya fue anulada previamente mediante nota crédito. Búscala más abajo en el historial.")
            else:
                st.warning(f"Vas a anular la factura #{numero_factura_anular} de esta orden. Esta acción no se puede deshacer.")
                with st.form("form_anular_factura"):
                    confirmar_anular = st.checkbox(
                        f"Entiendo que anular la factura #{numero_factura_anular} es irreversible y confirmo que quiero hacerlo."
                    )
                    anular_click = st.form_submit_button(
                        "Anular factura con nota crédito", type="primary", width='stretch'
                    )
                st.session_state["debug_anular_result"] = f"anular_click={anular_click} confirmar_anular={confirmar_anular}"
                if anular_click:
                    if not confirmar_anular:
                        st.warning("Marca la casilla de confirmación antes de anular la factura.")
                    else:
                        with st.spinner("Emitiendo nota crédito..."):
                            ok_nc, msg_nc = factus_utils.anular_factura_orden(user_id, hoja_id_anular)
                        st.session_state["debug_anular_result"] = f"ok_nc={ok_nc} msg_nc={msg_nc}"
                        if ok_nc:
                            st.success(msg_nc)
                            invalidar_cache_ordenes()
                        else:
                            st.error(msg_nc)
                        st.rerun()

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
            df_nc = df_nc[df_nc['numero_orden'].astype(str).str.contains(filtro_orden, case=False, na=False)]
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
            'numero_orden', 'nota_credito_fecha', 'placa', 'cliente', 'nit',
            'N° Factura', 'N° Nota Crédito', 'total'
        ]].rename(columns={
            'numero_orden': 'N° Orden', 'nota_credito_fecha': 'Fecha NC', 'placa': 'Placa',
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
            f"Orden #{r['numero_orden']} — {r['cliente']} (Placa {r['placa']}) — {formato_cop(r['total'])}": i
            for i, r in df_nc.iterrows()
        }
        nc_sel_str = st.selectbox("Selecciona una nota crédito", options=list(dict_nc.keys()))
        fila_nc = df_nc.loc[dict_nc[nc_sel_str]]

        col_dl1, col_dl2 = st.columns(2)
        factus_utils.mostrar_documento(
            col_dl1, "Descargar PDF", fila_nc['nota_credito_pdf_url'],
            f"NotaCredito_Orden_{fila_nc['numero_orden']}.pdf", "application/pdf"
        )
        factus_utils.mostrar_documento(
            col_dl2, "Descargar XML", fila_nc['nota_credito_xml_url'],
            f"NotaCredito_Orden_{fila_nc['numero_orden']}.xml", "application/xml"
        )
else:
    st.warning("Por favor selecciona un rango de fechas válido.")
