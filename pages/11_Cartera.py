from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from queries import (
    obtener_creditos_pendientes, obtener_abonos_orden, registrar_abono,
    obtener_deuda_por_empresa, obtener_ordenes_credito_empresa, obtener_abonos_empresa,
)
from db import mensaje_error_amigable
import factus_utils
import excel_utils

_mostrar_animacion_pagina = st.session_state.get("_ultima_pagina_animada") != "cartera"
st.session_state["_ultima_pagina_animada"] = "cartera"
_anim_pagina_css = (
    '<style>[data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out !important; }</style>'
    if _mostrar_animacion_pagina else ""
)

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
    [data-testid="stExpanderDetails"], [role="tabpanel"] { animation: fade-in-up 0.4s ease-out !important; }
    </style>
""" + _anim_pagina_css, unsafe_allow_html=True)

# --------------------------------------------------------------------------------
# AUTENTICACIÓN: mismo namespace st.session_state.auth definido en app.py
# --------------------------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

# Si el token de sesión no está en la URL (ej. tras navegar desde otra
# página), lo vuelve a agregar para que un F5 en esta misma página
# también recupere la sesión, sin depender solo de la cookie.
if "token" not in st.query_params and st.session_state.auth.get("token"):
    st.query_params["token"] = st.session_state.auth["token"]

# Bloqueo de rol: los operarios de Patio solo tienen acceso a Recepción.
if st.session_state.auth.get("rol") == "patio":
    st.warning("🔒 Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

st.title("Cartera")
st.markdown(f"Gestión de cartera y créditos para: **{nombre_taller}**")
st.markdown("---")

tab_activa, tab_clientes = st.tabs(["Cartera Activa", "Clientes con Cartera"])

# ==========================================
# PESTAÑA 1: CARTERA ACTIVA (análisis general + tabla completa + abonos)
# ==========================================
with tab_activa:
    df_creditos = obtener_creditos_pendientes(user_id)

    if df_creditos.empty:
        st.success("No hay órdenes con saldo pendiente a crédito en este momento. ¡Cartera limpia!")
    else:
        total_deuda = df_creditos['saldo_pendiente'].sum()
        vencidos = df_creditos[df_creditos['vencido'] == True]
        hoy = datetime.today().date()
        por_vencer = df_creditos[
            (df_creditos['vencido'] == False)
            & (pd.to_datetime(df_creditos['fecha_vencimiento_credito']) <= pd.Timestamp(hoy + timedelta(days=7)))
        ]

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Total en Cartera", formato_cop(total_deuda))
        col_m2.metric("Créditos Vencidos", len(vencidos), delta="Cobrar ya" if len(vencidos) > 0 else None, delta_color="inverse")
        col_m3.metric("Vencen esta semana", len(por_vencer), delta="Avisar" if len(por_vencer) > 0 else None, delta_color="inverse")
        col_m4.metric("Órdenes con saldo pendiente", len(df_creditos))

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
                "Descargar Excel de Cartera", data=excel_cartera,
                file_name=f"Cartera_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        st.markdown("---")
        st.subheader("Registrar Abono")

        dict_ordenes_credito = {
            f"Orden #{r['numero_orden']} — {r['cliente']} (Placa {r['placa']}) — Saldo: {formato_cop(r['saldo_pendiente'])}": r['hoja_id']
            for _, r in df_creditos.iterrows()
        }
        opciones_ordenes_credito = ["-- Seleccionar Empresa/Persona --"] + list(dict_ordenes_credito.keys())
        orden_sel_str = st.selectbox("Selecciona la orden a abonar", options=opciones_ordenes_credito)

        if orden_sel_str == "-- Seleccionar Empresa/Persona --":
            st.info("Selecciona una orden para registrar un abono.")
        else:
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

# ==========================================
# PESTAÑA 2: CLIENTES CON CARTERA (vista por cliente)
# ==========================================
with tab_clientes:
    st.subheader("Clientes con Saldo Pendiente")

    df_deuda_empresas = obtener_deuda_por_empresa(user_id)

    if df_deuda_empresas.empty:
        st.success("Ningún cliente tiene saldo pendiente actualmente. ¡Cartera limpia!")
    else:
        busq_cliente_cartera = st.text_input(
            "Buscar cliente", placeholder="Nombre del cliente...", key="busq_cliente_cartera"
        )
        df_deuda_mostrar = df_deuda_empresas.copy()
        if busq_cliente_cartera.strip():
            df_deuda_mostrar = df_deuda_mostrar[
                df_deuda_mostrar['cliente'].astype(str).str.lower().str.contains(
                    busq_cliente_cartera.strip().lower(), na=False
                )
            ]

        st.dataframe(
            df_deuda_mostrar.rename(columns={
                'cliente': 'Cliente', 'telefono': 'Teléfono',
                'deuda_actual': 'Deuda Actual', 'ordenes_con_deuda': 'Órdenes con Deuda',
            })[['Cliente', 'Teléfono', 'Deuda Actual', 'Órdenes con Deuda']],
            width='stretch', hide_index=True,
            column_config={"Deuda Actual": st.column_config.NumberColumn(format="$%,d")}
        )

        st.markdown("---")
        st.subheader("Detalle del Cliente")

        dict_empresas_deuda = {r['cliente']: r['empresa_id'] for _, r in df_deuda_empresas.iterrows()}
        opciones_clientes_cartera = ["-- Seleccionar Empresa/Persona --"] + list(dict_empresas_deuda.keys())
        cliente_sel_cartera = st.selectbox(
            "Selecciona un cliente para ver su detalle",
            options=opciones_clientes_cartera, key="cliente_sel_cartera"
        )

        if cliente_sel_cartera == "-- Seleccionar Empresa/Persona --":
            st.info("Selecciona un cliente para ver su detalle de cartera.")
        else:
            empresa_id_sel = dict_empresas_deuda[cliente_sel_cartera]
            df_ordenes_cliente = obtener_ordenes_credito_empresa(user_id, empresa_id_sel)
            df_abonos_cliente = obtener_abonos_empresa(user_id, empresa_id_sel)

            deuda_actual_cliente = df_ordenes_cliente['saldo_pendiente'].sum()
            total_abonado_cliente = df_abonos_cliente['monto'].sum() if not df_abonos_cliente.empty else 0
            ordenes_con_deuda_cliente = len(df_ordenes_cliente[df_ordenes_cliente['saldo_pendiente'] > 0])

            col_c1, col_c2, col_c3, col_c4 = st.columns(4)
            col_c1.metric("Deuda Actual", formato_cop(deuda_actual_cliente))
            col_c2.metric("Total Abonado (histórico)", formato_cop(total_abonado_cliente))
            col_c3.metric("Órdenes con Deuda", ordenes_con_deuda_cliente)
            col_c4.metric("Órdenes a Crédito (total)", len(df_ordenes_cliente))

            st.markdown("---")
            st.markdown(f"**Órdenes a crédito de {cliente_sel_cartera}:**")

            df_ord_mostrar = df_ordenes_cliente.copy()
            df_ord_mostrar['numero_factura_texto'] = (
                df_ord_mostrar['factura_prefijo'].fillna('').astype(str)
                + df_ord_mostrar['factura_numero'].fillna('').astype(str)
            )

            def _estado_factura_txt(row):
                if row['nota_credito_reference_code']:
                    return "Anulada (N.C.)"
                if row['factura_estado'] == 'emitida':
                    return "Facturada"
                if row['factura_estado'] == 'error':
                    return "Error factura"
                return "Sin facturar"

            df_ord_mostrar['facturacion'] = df_ord_mostrar.apply(_estado_factura_txt, axis=1)

            st.dataframe(
                df_ord_mostrar[[
                    'numero_orden', 'fecha', 'placa', 'total_orden', 'saldo_pendiente',
                    'fecha_vencimiento_credito', 'vencido', 'facturacion', 'numero_factura_texto'
                ]].rename(columns={
                    'numero_orden': 'N° Orden', 'fecha': 'Fecha', 'placa': 'Placa',
                    'total_orden': 'Total Orden', 'saldo_pendiente': 'Saldo Pendiente',
                    'fecha_vencimiento_credito': 'Fecha Vencimiento', 'vencido': 'Vencido',
                    'facturacion': 'Facturación', 'numero_factura_texto': 'N° Factura',
                }),
                width='stretch', hide_index=True,
                column_config={
                    "Total Orden": st.column_config.NumberColumn(format="$%,d"),
                    "Saldo Pendiente": st.column_config.NumberColumn(format="$%,d"),
                }
            )

            st.markdown("---")
            st.markdown("**Historial de abonos:**")
            if df_abonos_cliente.empty:
                st.caption(f"{cliente_sel_cartera} todavía no ha hecho ningún abono.")
            else:
                st.dataframe(
                    df_abonos_cliente.rename(columns={
                        'monto': 'Monto', 'fecha': 'Fecha', 'notas': 'Notas', 'numero_orden': 'N° Orden',
                    })[['Fecha', 'N° Orden', 'Monto', 'Notas']],
                    width='stretch', hide_index=True,
                    column_config={"Monto": st.column_config.NumberColumn(format="$%,d")}
                )

            ordenes_pendientes_cliente = df_ordenes_cliente[df_ordenes_cliente['saldo_pendiente'] > 0]
            if not ordenes_pendientes_cliente.empty:
                st.markdown("---")
                st.markdown("**Registrar Abono para este cliente:**")

                dict_ordenes_cliente = {
                    f"Orden #{r['numero_orden']} — Saldo: {formato_cop(r['saldo_pendiente'])}": r['hoja_id']
                    for _, r in ordenes_pendientes_cliente.iterrows()
                }
                opciones_ord_cliente = ["-- Seleccionar Orden --"] + list(dict_ordenes_cliente.keys())
                orden_abono_cliente_sel = st.selectbox(
                    "Selecciona la orden a abonar", options=opciones_ord_cliente, key="orden_abono_cliente_sel"
                )

                if orden_abono_cliente_sel != "-- Seleccionar Orden --":
                    hoja_id_cliente_sel = dict_ordenes_cliente[orden_abono_cliente_sel]
                    fila_orden_cliente = ordenes_pendientes_cliente[
                        ordenes_pendientes_cliente['hoja_id'] == hoja_id_cliente_sel
                    ].iloc[0]
                    saldo_cliente_actual = float(fila_orden_cliente['saldo_pendiente'])

                    factus_utils.mostrar_documento(
                        st, "Descargar factura de esta orden", fila_orden_cliente['factura_pdf_url'],
                        f"Factura_Orden_{fila_orden_cliente['numero_orden']}.pdf", "application/pdf"
                    )

                    col_ca1, col_ca2 = st.columns(2)
                    with col_ca1:
                        monto_abono_cliente = st.number_input(
                            "Monto del abono", min_value=0, max_value=int(saldo_cliente_actual), step=5000, value=0,
                            key="monto_abono_cliente"
                        )
                        metodo_abono_cliente = st.selectbox(
                            "Método de pago", ["Efectivo", "Transferencia"], key="metodo_abono_cliente"
                        )
                    with col_ca2:
                        notas_abono_cliente = st.text_area("Notas (opcional)", key="notas_abono_cliente")

                    if st.button("Registrar Abono", type="primary", width='stretch', key="btn_abono_cliente"):
                        if monto_abono_cliente <= 0:
                            st.warning("Escribe cuánto pagó el cliente. El monto debe ser mayor a cero.")
                        else:
                            try:
                                nota_completa_c = (
                                    f"[{metodo_abono_cliente}] {notas_abono_cliente}".strip()
                                    if notas_abono_cliente else f"[{metodo_abono_cliente}]"
                                )
                                with st.spinner("Registrando abono..."):
                                    registrar_abono(user_id, hoja_id_cliente_sel, monto_abono_cliente, nota_completa_c)
                                st.success(f"Abono de {formato_cop(monto_abono_cliente)} registrado.")
                                st.rerun()
                            except Exception as e:
                                st.error(mensaje_error_amigable(e, "registrar el abono"))
