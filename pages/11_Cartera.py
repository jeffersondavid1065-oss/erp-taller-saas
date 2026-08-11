from datetime import datetime
import streamlit as st
from queries import obtener_creditos_pendientes, obtener_abonos_orden, registrar_abono
from db import mensaje_error_amigable
import factus_utils
import excel_utils

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
    return f"${float(numero):,.0f}".replace(",", ".")

st.title("Cartera")
st.markdown(f"Órdenes facturadas a crédito para: **{nombre_taller}**")
st.markdown("---")

df_creditos = obtener_creditos_pendientes(user_id)

if df_creditos.empty:
    st.info("No hay órdenes con saldo pendiente a crédito en este momento.")
else:
    total_deuda = df_creditos['saldo_pendiente'].sum()
    vencidos = df_creditos[df_creditos['vencido'] == True]

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total en Cartera", formato_cop(total_deuda))
    col_m2.metric("Créditos Vencidos", len(vencidos), delta="Cobrar ya" if len(vencidos) > 0 else None, delta_color="inverse")
    col_m3.metric("Órdenes con saldo pendiente", len(df_creditos))

    st.markdown("---")

    if not vencidos.empty:
        st.error(f"**{len(vencidos)} orden(es) con crédito vencido:**")
        for _, v in vencidos.iterrows():
            st.write(
                f"• Orden **#{v['numero_orden']}** — {v['cliente']} (Placa {v['placa']}) — "
                f"Saldo: {formato_cop(v['saldo_pendiente'])} — Venció: {v['fecha_vencimiento_credito']}"
            )
        st.markdown("---")

    st.markdown("**Todas las órdenes con saldo pendiente:**")
    busqueda_cartera = st.text_input(
        "Buscar por cliente, placa o N° de orden",
        placeholder="Ej: Pérez, ABC123 o 45",
        key="busqueda_cartera"
    )
    df_mostrar = df_creditos.copy()
    if busqueda_cartera.strip():
        termino = busqueda_cartera.strip().lower()
        df_mostrar = df_mostrar[
            df_mostrar['cliente'].astype(str).str.lower().str.contains(termino, na=False)
            | df_mostrar['placa'].astype(str).str.lower().str.contains(termino, na=False)
            | df_mostrar['numero_orden'].astype(str).str.contains(termino, na=False)
        ]
    df_mostrar['numero_factura_texto'] = (
        df_mostrar['factura_prefijo'].fillna('').astype(str) + df_mostrar['factura_numero'].fillna('').astype(str)
    )
    if df_mostrar.empty:
        st.info("Ninguna orden coincide con la búsqueda.")
    df_mostrar = df_mostrar[[
        'numero_orden', 'placa', 'cliente', 'telefono', 'saldo_pendiente',
        'fecha_vencimiento_credito', 'vencido', 'numero_factura_texto'
    ]].rename(columns={
        'numero_orden': 'N° Orden', 'placa': 'Placa', 'cliente': 'Cliente', 'telefono': 'Teléfono',
        'saldo_pendiente': 'Saldo Pendiente', 'fecha_vencimiento_credito': 'Fecha Vencimiento',
        'vencido': 'Vencido', 'numero_factura_texto': 'N° Factura',
    })
    st.dataframe(
        df_mostrar,
        width='stretch', hide_index=True,
        column_config={
            "Saldo Pendiente": st.column_config.NumberColumn(format="$%,d"),
        }
    )
    st.caption("Para descargar la factura de una orden específica, selecciónala abajo en \"Registrar Abono\".")

    if not df_mostrar.empty:
        excel_cartera = excel_utils.generar_excel_tabla(
            df_mostrar, "Cartera - Créditos Pendientes", nombre_taller,
            columnas_moneda=["Saldo Pendiente"], nombre_hoja="Cartera", columna_total="Saldo Pendiente"
        )
        st.download_button(
            "📥 Descargar Excel de Cartera", data=excel_cartera,
            file_name=f"Cartera_{datetime.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.markdown("---")
    st.subheader("Registrar Abono")

    dict_ordenes_credito = {
        f"Orden #{r['numero_orden']} — {r['cliente']} (Placa {r['placa']}) — Saldo: {formato_cop(r['saldo_pendiente'])}": r['hoja_id']
        for _, r in df_creditos.iterrows()
    }
    orden_sel_str = st.selectbox("Selecciona la orden a abonar", options=list(dict_ordenes_credito.keys()))
    hoja_id_sel = dict_ordenes_credito[orden_sel_str]
    fila_credito_sel = df_creditos[df_creditos['hoja_id'] == hoja_id_sel].iloc[0]
    saldo_actual = float(fila_credito_sel['saldo_pendiente'])
    numero_orden_sel = fila_credito_sel['numero_orden']

    factus_utils.mostrar_documento(
        st, "Descargar factura de esta orden", fila_credito_sel['factura_pdf_url'],
        f"Factura_Orden_{numero_orden_sel}.pdf", "application/pdf"
    )

    st.caption(f"Saldo pendiente de esta orden: **{formato_cop(saldo_actual)}**")

    col_ab1, col_ab2 = st.columns(2)
    with col_ab1:
        monto_abono = st.number_input(
            "Monto del abono", min_value=0, max_value=int(saldo_actual), step=5000, value=0,
            help=(
                "Un 'abono' es un pago parcial de la deuda del cliente. Escribe cuánto pagó "
                "ahora — si pagó todo, escribe el saldo pendiente completo."
            )
        )
        metodo_abono = st.selectbox("Método de pago", ["Efectivo", "Transferencia"])
    with col_ab2:
        notas_abono = st.text_area("Notas (opcional)", placeholder="Ej: Pago parcial en efectivo en taller")

    if st.button("Registrar Abono", type="primary", width='stretch'):
        if monto_abono <= 0:
            st.warning("Escribe cuánto pagó el cliente. El monto debe ser mayor a cero.")
        else:
            try:
                nota_completa = f"[{metodo_abono}] {notas_abono}".strip() if notas_abono else f"[{metodo_abono}]"
                with st.spinner("Registrando abono..."):
                    registrar_abono(user_id, hoja_id_sel, monto_abono, nota_completa)
                st.success(f"Abono de {formato_cop(monto_abono)} registrado.")
                st.rerun()
            except Exception as e:
                st.error(mensaje_error_amigable(e, "registrar el abono"))

    with st.expander(f"Historial de abonos de la Orden #{numero_orden_sel}"):
        abonos = obtener_abonos_orden(hoja_id_sel)
        if not abonos:
            st.caption("Todavía no se ha registrado ningún abono para esta orden.")
        else:
            for ab in abonos:
                nota_txt = f" — {ab.notas}" if ab.notas else ""
                st.write(f"• {formato_cop(ab.monto)} el {ab.fecha}{nota_txt}")
