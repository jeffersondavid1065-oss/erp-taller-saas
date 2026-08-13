from datetime import datetime, timedelta, date
import pandas as pd
import streamlit as st
from queries import (
    obtener_creditos_pendientes, obtener_abonos_orden, registrar_abono,
    obtener_deuda_por_empresa, obtener_ordenes_credito_empresa, obtener_abonos_empresa,
    obtener_empresas_directorio, obtener_config_taller,
)
from db import mensaje_error_amigable
from pdf_utils import generar_pdf_estado_cuenta
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

    /* Aparición sutil del detalle al seleccionar un cliente (Clientes con
       Cartera / Estado de Cuenta): fundido corto y casi sin desplazamiento,
       a propósito más discreto que fade-in-up. */
    @keyframes fade-in-subtle {
        0% { opacity: 0; transform: translateY(6px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    .st-key-detalle_cliente_cartera, .st-key-detalle_estado_cuenta {
        animation: fade-in-subtle 0.35s ease-out;
    }
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

tab_activa, tab_clientes, tab_estado_cuenta = st.tabs(
    ["Cartera Activa", "Clientes con Cartera", "Estado de Cuenta"]
)

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
            with st.container(key="detalle_cliente_cartera"):
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

# ==========================================
# PESTAÑA 3: ESTADO DE CUENTA (PDF por cliente y período)
# ==========================================
with tab_estado_cuenta:
    st.subheader("Generar Estado de Cuenta")
    st.caption(
        "Genera un estado de cuenta en PDF para enviarle a cualquier cliente: sirve tanto para "
        "mostrarle lo que debe como para confirmarle que ya está al día (paz y salvo)."
    )

    df_empresas_ec = obtener_empresas_directorio(user_id)

    if df_empresas_ec.empty:
        st.info("Tu taller aún no tiene clientes registrados.")
    else:
        dict_empresas_ec = {r['razon_social']: r['id'] for _, r in df_empresas_ec.iterrows()}
        opciones_empresas_ec = ["-- Seleccionar Empresa/Persona --"] + list(dict_empresas_ec.keys())

        col_ec1, col_ec2, col_ec3 = st.columns([2, 1, 1])
        with col_ec1:
            cliente_ec_sel = st.selectbox("Cliente", options=opciones_empresas_ec, key="cliente_ec_sel")
        with col_ec2:
            fecha_desde_ec = st.date_input(
                "Desde", value=date.today() - timedelta(days=90), key="fecha_desde_ec"
            )
        with col_ec3:
            fecha_hasta_ec = st.date_input("Hasta", value=date.today(), key="fecha_hasta_ec")

        if cliente_ec_sel == "-- Seleccionar Empresa/Persona --":
            st.info("Selecciona un cliente para generar su estado de cuenta.")
        elif fecha_desde_ec > fecha_hasta_ec:
            st.error("La fecha 'Desde' no puede ser posterior a la fecha 'Hasta'.")
        else:
            with st.container(key="detalle_estado_cuenta"):
                empresa_id_ec = dict_empresas_ec[cliente_ec_sel]
                fila_empresa_ec = df_empresas_ec[df_empresas_ec['id'] == empresa_id_ec].iloc[0]

                df_ordenes_ec = obtener_ordenes_credito_empresa(user_id, empresa_id_ec)
                df_abonos_ec = obtener_abonos_empresa(user_id, empresa_id_ec)

                eventos = []
                for _, r in df_ordenes_ec.iterrows():
                    eventos.append({
                        "fecha": pd.to_datetime(r['fecha']).date(),
                        "descripcion": f"Orden #{r['numero_orden']} — Placa {r['placa']}",
                        "cargo": float(r['total_orden']),
                        "abono": 0.0,
                    })
                for _, r in df_abonos_ec.iterrows():
                    nota_txt = f" ({r['notas']})" if r.get('notas') else ""
                    eventos.append({
                        "fecha": pd.to_datetime(r['fecha']).date(),
                        "descripcion": f"Abono Orden #{r['numero_orden']}{nota_txt}",
                        "cargo": 0.0,
                        "abono": float(r['monto']),
                    })
                eventos.sort(key=lambda e: e['fecha'])

                saldo_anterior_ec = sum(e['cargo'] - e['abono'] for e in eventos if e['fecha'] < fecha_desde_ec)
                movimientos_periodo = [e for e in eventos if fecha_desde_ec <= e['fecha'] <= fecha_hasta_ec]

                saldo_corriente_ec = saldo_anterior_ec
                filas_preview = []
                for ev in movimientos_periodo:
                    saldo_corriente_ec += ev['cargo'] - ev['abono']
                    filas_preview.append({
                        "Fecha": ev['fecha'].strftime("%d/%m/%Y"),
                        "Descripción": ev['descripcion'],
                        "Cargo": ev['cargo'],
                        "Abono": ev['abono'],
                        "Saldo": saldo_corriente_ec,
                    })
                saldo_final_ec = saldo_corriente_ec

                total_cargos_periodo = sum(e['cargo'] for e in movimientos_periodo)
                total_abonos_periodo = sum(e['abono'] for e in movimientos_periodo)

                st.markdown("---")
                col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                col_r1.metric("Saldo Anterior", formato_cop(saldo_anterior_ec))
                col_r2.metric("Cargos del Período", formato_cop(total_cargos_periodo))
                col_r3.metric("Abonos del Período", formato_cop(total_abonos_periodo))
                col_r4.metric("Saldo Final", formato_cop(saldo_final_ec))

                if saldo_final_ec <= 0:
                    st.success(f"{cliente_ec_sel} está al día — sin saldo pendiente.")
                else:
                    st.warning(f"{cliente_ec_sel} tiene un saldo pendiente de {formato_cop(saldo_final_ec)}.")

                st.markdown("---")
                st.markdown("**Movimientos del período:**")
                if not filas_preview:
                    st.caption("Sin movimientos registrados en este período.")
                else:
                    st.dataframe(
                        pd.DataFrame(filas_preview),
                        width='stretch', hide_index=True,
                        column_config={
                            "Cargo": st.column_config.NumberColumn(format="$%,d"),
                            "Abono": st.column_config.NumberColumn(format="$%,d"),
                            "Saldo": st.column_config.NumberColumn(format="$%,d"),
                        }
                    )

                st.markdown("---")

                _config_taller_ec = obtener_config_taller(user_id)
                logo_path_ec = _config_taller_ec[3] if _config_taller_ec and _config_taller_ec[3] else None
                taller_nit_ec = _config_taller_ec[8] if _config_taller_ec and len(_config_taller_ec) > 8 and _config_taller_ec[8] else ""
                taller_telefono_ec = _config_taller_ec[9] if _config_taller_ec and len(_config_taller_ec) > 9 and _config_taller_ec[9] else ""
                taller_direccion_raw_ec = _config_taller_ec[10] if _config_taller_ec and len(_config_taller_ec) > 10 and _config_taller_ec[10] else ""
                taller_ciudad_ec = _config_taller_ec[11] if _config_taller_ec and len(_config_taller_ec) > 11 and _config_taller_ec[11] else ""
                taller_direccion_ec = f"{taller_direccion_raw_ec}, {taller_ciudad_ec}".strip(", ") if taller_ciudad_ec else taller_direccion_raw_ec
                taller_email_ec = _config_taller_ec[2] if _config_taller_ec and _config_taller_ec[2] else ""

                pdf_bytes_ec = generar_pdf_estado_cuenta(
                    taller_nombre=nombre_taller,
                    taller_nit=taller_nit_ec,
                    taller_telefono=taller_telefono_ec,
                    taller_direccion=taller_direccion_ec,
                    taller_email=taller_email_ec,
                    taller_logo_path=logo_path_ec,
                    cliente=cliente_ec_sel,
                    cliente_nit=fila_empresa_ec.get('nit', ''),
                    cliente_telefono=fila_empresa_ec.get('telefono', ''),
                    fecha_desde=fecha_desde_ec.strftime("%d/%m/%Y"),
                    fecha_hasta=fecha_hasta_ec.strftime("%d/%m/%Y"),
                    fecha_generacion=datetime.today().strftime("%d/%m/%Y"),
                    saldo_anterior=saldo_anterior_ec,
                    movimientos=[
                        {"fecha": ev['fecha'].strftime("%d/%m/%Y"), "descripcion": ev['descripcion'],
                         "cargo": ev['cargo'], "abono": ev['abono']}
                        for ev in movimientos_periodo
                    ],
                    saldo_final=saldo_final_ec,
                )

                st.download_button(
                    "Descargar Estado de Cuenta en PDF",
                    data=pdf_bytes_ec,
                    file_name=f"Estado_Cuenta_{cliente_ec_sel.replace(' ', '_')}_{datetime.today().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    width='stretch'
                )
