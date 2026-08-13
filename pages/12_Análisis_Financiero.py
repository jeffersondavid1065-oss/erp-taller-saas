import streamlit as st
import pandas as pd
import calendar
from datetime import datetime, timedelta
from queries import (
    obtener_resumen_financiero_periodo, obtener_iva_por_tasa_periodo, obtener_gastos_por_categoria,
    obtener_gastos_filtrado, obtener_desglose_mano_obra_repuestos, obtener_tendencia_mensual,
)
import excel_utils

_mostrar_animacion_pagina = st.session_state.get("_ultima_pagina_animada") != "analisis_financiero"
st.session_state["_ultima_pagina_animada"] = "analisis_financiero"
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

def formato_delta_pct(actual, anterior):
    """Texto de comparación porcentual contra el período anterior, para el
    parámetro `delta` de st.metric. None si no hay base de comparación."""
    if not anterior:
        return None
    cambio = (actual - anterior) / abs(anterior) * 100
    return f"{cambio:+.1f}% vs período anterior"

st.title("Análisis Financiero")
st.markdown(f"Cómo está el taller en términos económicos: **{nombre_taller}**")
st.markdown("---")

hoy = datetime.today()
hace_30_dias = hoy - timedelta(days=30)
fechas_filtro = st.date_input("Período a analizar", [hace_30_dias, hoy])

if len(fechas_filtro) != 2:
    st.warning("Por favor selecciona un rango de fechas válido.")
    st.stop()

fecha_inicio, fecha_fin = fechas_filtro

tab_resumen, tab_tendencia, tab_rentabilidad, tab_iva = st.tabs([
    "Resumen del Negocio", "Tendencia Mensual", "Rentabilidad y Punto de Equilibrio", "Declarar IVA"
])

# ==========================================
# TAB 1: RESUMEN DEL NEGOCIO
# ==========================================
with tab_resumen:
    resumen = obtener_resumen_financiero_periodo(user_id, fecha_inicio, fecha_fin)

    # Comparación con el período inmediatamente anterior, de la misma duración.
    dias_periodo = (fecha_fin - fecha_inicio).days + 1
    fecha_fin_anterior = fecha_inicio - timedelta(days=1)
    fecha_inicio_anterior = fecha_fin_anterior - timedelta(days=dias_periodo - 1)
    resumen_anterior = obtener_resumen_financiero_periodo(user_id, fecha_inicio_anterior, fecha_fin_anterior)

    st.caption(
        "Los ingresos, la utilidad bruta y la utilidad neta ya están calculados **sin el IVA cobrado**: "
        "ese IVA no es ganancia del taller, es dinero que hay que entregarle a la DIAN "
        "(revisa cuánto en la pestaña 'Declarar IVA'). Los porcentajes de cambio comparan contra el "
        f"período inmediatamente anterior de la misma duración ({fecha_inicio_anterior.strftime('%d/%m/%Y')} "
        f"a {fecha_fin_anterior.strftime('%d/%m/%Y')})."
    )

    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric(
        "Órdenes Facturadas", resumen["num_ordenes"],
        delta=formato_delta_pct(resumen["num_ordenes"], resumen_anterior["num_ordenes"])
    )
    ticket_promedio = resumen["ingresos"] / resumen["num_ordenes"] if resumen["num_ordenes"] else 0
    ticket_promedio_anterior = (
        resumen_anterior["ingresos"] / resumen_anterior["num_ordenes"] if resumen_anterior["num_ordenes"] else 0
    )
    col_r2.metric(
        "Ticket Promedio (ARO)", formato_cop(ticket_promedio),
        delta=formato_delta_pct(ticket_promedio, ticket_promedio_anterior),
        help="ARO = Average Repair Order, el ticket promedio por orden facturada. Es uno de los indicadores más usados para medir la salud de un taller."
    )
    col_r3.metric("IVA Recaudado (no es ingreso)", formato_cop(resumen["iva_recaudado"]))

    st.markdown("---")
    st.markdown("**De ingresos a utilidad neta:**")

    col_u1, col_u2, col_u3, col_u4, col_u5 = st.columns(5)
    col_u1.metric(
        "Ingresos", formato_cop(resumen["ingresos"]),
        delta=formato_delta_pct(resumen["ingresos"], resumen_anterior["ingresos"])
    )
    col_u2.metric(
        "Costo Directo", formato_cop(resumen["costo_directo"]), delta=f"-{formato_cop(resumen['costo_directo'])}"
    )
    col_u3.metric(
        "Utilidad Bruta", formato_cop(resumen["utilidad_bruta"]),
        delta=formato_delta_pct(resumen["utilidad_bruta"], resumen_anterior["utilidad_bruta"])
    )
    col_u4.metric(
        "Gastos Operativos", formato_cop(resumen["gastos"]), delta=f"-{formato_cop(resumen['gastos'])}"
    )
    col_u5.metric(
        "Utilidad Neta", formato_cop(resumen["utilidad_neta"]),
        delta=formato_delta_pct(resumen["utilidad_neta"], resumen_anterior["utilidad_neta"]),
        delta_color="inverse" if resumen["utilidad_neta"] < 0 else "normal"
    )

    if resumen["ingresos"] > 0:
        pct_utilidad = (resumen["utilidad_neta"] / resumen["ingresos"]) * 100
        st.caption(f"Margen neto sobre ingresos: **{pct_utilidad:.1f}%**")

    st.markdown("---")
    st.markdown("**Mano de Obra vs Repuestos:**")
    st.caption(
        "En un taller sano el margen de mano de obra suele ser más alto que el de repuestos — "
        "verlos mezclados esconde si alguna de las dos líneas está perdiendo rentabilidad."
    )

    desglose = obtener_desglose_mano_obra_repuestos(user_id, fecha_inicio, fecha_fin)
    mano_obra, repuestos = desglose["Mano de Obra"], desglose["Repuesto"]

    col_mo, col_rep = st.columns(2)
    with col_mo:
        st.markdown("**Mano de Obra**")
        st.metric("Ingresos", formato_cop(mano_obra["ingresos"]))
        st.metric("Margen", formato_cop(mano_obra["margen"]), f"{mano_obra['margen_pct']:.1f}% margen")
        st.caption(f"{mano_obra['cantidad']} ítem(s) facturado(s) en el período")
    with col_rep:
        st.markdown("**Repuestos**")
        st.metric("Ingresos", formato_cop(repuestos["ingresos"]))
        st.metric("Margen", formato_cop(repuestos["margen"]), f"{repuestos['margen_pct']:.1f}% margen")
        st.caption(f"{repuestos['cantidad']} ítem(s) facturado(s) en el período")

    if mano_obra["ingresos"] > 0:
        ratio_rep_mo = repuestos["ingresos"] / mano_obra["ingresos"]
        st.caption(
            f"Relación Repuestos/Mano de Obra: **{ratio_rep_mo:.2f}** "
            "(referencia saludable en talleres: entre 0.8 y 1.0 — por cada $1 de mano de obra, "
            "entre $0.80 y $1 en repuestos)."
        )

    st.markdown("---")
    st.markdown("**Gastos Fijos vs Variables:**")
    df_gastos_periodo = obtener_gastos_filtrado(user_id, fecha_inicio, fecha_fin)
    if not df_gastos_periodo.empty:
        gastos_fijos = float(df_gastos_periodo[df_gastos_periodo['tipo'] == 'Fijo']['monto'].sum())
        gastos_variables = float(df_gastos_periodo[df_gastos_periodo['tipo'] == 'Variable']['monto'].sum())
        col_gf, col_gv = st.columns(2)
        col_gf.metric("Gastos Fijos", formato_cop(gastos_fijos))
        col_gv.metric("Gastos Variables", formato_cop(gastos_variables))
    else:
        gastos_fijos = gastos_variables = 0.0
        st.info("No hay gastos registrados en este período.")

    st.markdown("---")
    st.markdown("**Gastos por categoría en el período:**")
    df_gastos_cat = obtener_gastos_por_categoria(user_id, fecha_inicio, fecha_fin)
    if not df_gastos_cat.empty:
        st.bar_chart(df_gastos_cat.set_index('nombre')['total'], height=300)
    else:
        st.info("No hay gastos registrados en este período.")

    st.markdown("---")
    st.markdown("**Descargar reporte del período:**")
    df_resumen_export = pd.DataFrame([
        {"Concepto": "Ingresos (sin IVA)", "Valor": resumen["ingresos"]},
        {"Concepto": "Costo Directo", "Valor": resumen["costo_directo"]},
        {"Concepto": "Utilidad Bruta", "Valor": resumen["utilidad_bruta"]},
        {"Concepto": "Gastos Operativos", "Valor": resumen["gastos"]},
        {"Concepto": "Utilidad Neta", "Valor": resumen["utilidad_neta"]},
        {"Concepto": "IVA Recaudado", "Valor": resumen["iva_recaudado"]},
        {"Concepto": "Ingresos Mano de Obra", "Valor": mano_obra["ingresos"]},
        {"Concepto": "Margen Mano de Obra", "Valor": mano_obra["margen"]},
        {"Concepto": "Ingresos Repuestos", "Valor": repuestos["ingresos"]},
        {"Concepto": "Margen Repuestos", "Valor": repuestos["margen"]},
        {"Concepto": "Gastos Fijos", "Valor": gastos_fijos},
        {"Concepto": "Gastos Variables", "Valor": gastos_variables},
    ])
    excel_resumen = excel_utils.generar_excel_tabla(
        df_resumen_export, "Resumen Financiero", nombre_taller,
        columnas_moneda=["Valor"], nombre_hoja="Resumen"
    )
    st.download_button(
        "Descargar Resumen Financiero en Excel", data=excel_resumen,
        file_name=f"Resumen_Financiero_{fecha_inicio}_{fecha_fin}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width='stretch'
    )

# ==========================================
# TAB 2: TENDENCIA MENSUAL
# ==========================================
with tab_tendencia:
    st.subheader("Tendencia de los Últimos Meses")
    st.caption(
        "Cómo evolucionan ingresos, costos, gastos y utilidad mes a mes — útil para detectar si el "
        "negocio está mejorando o empeorando, algo que una sola foto de un período no muestra."
    )

    meses_tendencia = st.slider("Meses a mostrar", min_value=3, max_value=12, value=6, key="meses_tendencia")
    df_tendencia = obtener_tendencia_mensual(user_id, meses_tendencia)

    st.line_chart(df_tendencia.set_index("Mes")[["Ingresos", "Utilidad Neta"]], height=350)

    st.markdown("---")
    st.markdown("**Detalle mensual:**")
    st.dataframe(
        df_tendencia, width='stretch', hide_index=True,
        column_config={
            col: st.column_config.NumberColumn(format="$%,d")
            for col in ["Ingresos", "Costo Directo", "Gastos", "Utilidad Neta"]
        }
    )

    if not df_tendencia.empty:
        excel_tendencia = excel_utils.generar_excel_tabla(
            df_tendencia, f"Tendencia Financiera - Últimos {meses_tendencia} Meses", nombre_taller,
            columnas_moneda=["Ingresos", "Costo Directo", "Gastos", "Utilidad Neta"],
            nombre_hoja="Tendencia"
        )
        st.download_button(
            "Descargar Tendencia en Excel", data=excel_tendencia,
            file_name=f"Tendencia_Financiera_{meses_tendencia}m.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch'
        )

# ==========================================
# TAB 3: RENTABILIDAD Y PUNTO DE EQUILIBRIO
# ==========================================
with tab_rentabilidad:
    st.subheader("Rentabilidad y Punto de Equilibrio")
    st.caption(
        f"Basado en el período seleccionado arriba ({fecha_inicio.strftime('%d/%m/%Y')} a "
        f"{fecha_fin.strftime('%d/%m/%Y')})."
    )

    resumen_pe = obtener_resumen_financiero_periodo(user_id, fecha_inicio, fecha_fin)
    df_gastos_pe = obtener_gastos_filtrado(user_id, fecha_inicio, fecha_fin)
    gastos_fijos_pe = float(df_gastos_pe[df_gastos_pe['tipo'] == 'Fijo']['monto'].sum()) if not df_gastos_pe.empty else 0.0
    gastos_variables_pe = float(df_gastos_pe[df_gastos_pe['tipo'] == 'Variable']['monto'].sum()) if not df_gastos_pe.empty else 0.0

    ingresos_pe = resumen_pe["ingresos"]
    costos_variables_totales = resumen_pe["costo_directo"] + gastos_variables_pe
    margen_contribucion_pct = (ingresos_pe - costos_variables_totales) / ingresos_pe if ingresos_pe > 0 else 0.0

    col_pe1, col_pe2, col_pe3 = st.columns(3)
    col_pe1.metric("Margen de Contribución", f"{margen_contribucion_pct * 100:.1f}%")
    col_pe2.metric("Costos Fijos", formato_cop(gastos_fijos_pe))
    col_pe3.metric("Costos Variables", formato_cop(costos_variables_totales))

    st.caption(
        "Margen de Contribución = (Ingresos − Costos Variables) / Ingresos. Costos variables = costo "
        "directo de mano de obra y repuestos + gastos marcados como 'Variable'. Costos fijos = gastos "
        "marcados como 'Fijo' en Gastos y Análisis."
    )

    st.markdown("---")

    if margen_contribucion_pct > 0:
        punto_equilibrio = gastos_fijos_pe / margen_contribucion_pct
        st.metric("Punto de Equilibrio en Ventas (del período)", formato_cop(punto_equilibrio))
        if ingresos_pe >= punto_equilibrio:
            st.success(
                f"✅ En este período superaste tu punto de equilibrio por "
                f"{formato_cop(ingresos_pe - punto_equilibrio)}."
            )
        else:
            st.warning(
                f"⚠️ Te faltan {formato_cop(punto_equilibrio - ingresos_pe)} en ventas para cubrir "
                "tus costos fijos de este período."
            )
    else:
        st.info(
            "No se puede calcular el punto de equilibrio: no hay margen de contribución positivo en "
            "este período (los costos variables superan o igualan a los ingresos)."
        )

    st.markdown("---")
    st.markdown("**Margen bruto por línea de negocio:**")
    desglose_pe = obtener_desglose_mano_obra_repuestos(user_id, fecha_inicio, fecha_fin)
    df_margen_lineas = pd.DataFrame([
        {"Línea": "Mano de Obra", "Margen %": desglose_pe["Mano de Obra"]["margen_pct"]},
        {"Línea": "Repuestos", "Margen %": desglose_pe["Repuesto"]["margen_pct"]},
    ])
    st.bar_chart(df_margen_lineas.set_index("Línea")["Margen %"], height=250)

# ==========================================
# TAB 4: DECLARAR IVA
# ==========================================
with tab_iva:
    st.subheader("IVA a Declarar")
    st.caption(
        "Desglose del IVA generado en el período, por tasa - es el mismo dato que necesitas "
        "para la casilla de IVA Generado de tu declaración de IVA (Formulario 300). "
        "Este dinero ya fue cobrado a tus clientes, pero no es utilidad del taller: hay que "
        "entregárselo a la DIAN."
    )

    modo_periodo_iva = st.radio(
        "Período a usar para el IVA",
        ["Usar el período seleccionado arriba", "Bimestral", "Cuatrimestral"],
        horizontal=True, key="modo_periodo_iva"
    )

    PERIODICIDADES_IVA = {
        "Bimestral": {
            "Bimestre 1 (Ene-Feb)": (1, 2), "Bimestre 2 (Mar-Abr)": (3, 4),
            "Bimestre 3 (May-Jun)": (5, 6), "Bimestre 4 (Jul-Ago)": (7, 8),
            "Bimestre 5 (Sep-Oct)": (9, 10), "Bimestre 6 (Nov-Dic)": (11, 12),
        },
        "Cuatrimestral": {
            "Cuatrimestre 1 (Ene-Abr)": (1, 4),
            "Cuatrimestre 2 (May-Ago)": (5, 8),
            "Cuatrimestre 3 (Sep-Dic)": (9, 12),
        },
    }

    if modo_periodo_iva in PERIODICIDADES_IVA:
        st.caption(
            "La DIAN asigna la periodicidad según tus ingresos brutos del año anterior (Art. 600 E.T.): "
            "la mayoría de responsables declaran bimestral; los negocios más pequeños, cuatrimestral. "
            "Si no sabes cuál te aplica, revisa tu RUT o pregúntale a tu contador."
        )
        col_iva_p, col_iva_a = st.columns(2)
        opciones_periodo_iva = PERIODICIDADES_IVA[modo_periodo_iva]
        with col_iva_p:
            periodo_sel_iva = st.selectbox(
                modo_periodo_iva, options=list(opciones_periodo_iva.keys()),
                key=f"periodo_iva_sel_{modo_periodo_iva}"
            )
        with col_iva_a:
            año_iva_sel = st.number_input(
                "Año", min_value=2020, max_value=2100, value=hoy.year, step=1, key="anio_iva_sel"
            )
        mes_ini_iva, mes_fin_iva = opciones_periodo_iva[periodo_sel_iva]
        f_ini_iva = datetime(int(año_iva_sel), mes_ini_iva, 1).date()
        f_fin_iva = datetime(int(año_iva_sel), mes_fin_iva, calendar.monthrange(int(año_iva_sel), mes_fin_iva)[1]).date()
    else:
        f_ini_iva, f_fin_iva = fecha_inicio, fecha_fin

    st.markdown(f"**Período:** {f_ini_iva.strftime('%d/%m/%Y')} a {f_fin_iva.strftime('%d/%m/%Y')}")
    st.markdown("---")

    df_iva = obtener_iva_por_tasa_periodo(user_id, f_ini_iva, f_fin_iva)

    if df_iva.empty:
        st.info("No se generó IVA en este período (o el taller no tiene el IVA activado en Configuración).")
    else:
        st.dataframe(
            df_iva,
            width='stretch', hide_index=True,
            column_config={
                "Base Gravable": st.column_config.NumberColumn(format="$%,d"),
                "IVA Generado": st.column_config.NumberColumn(format="$%,d"),
            }
        )
        total_iva = df_iva["IVA Generado"].sum()
        st.metric("Total IVA a declarar en el período", formato_cop(total_iva))

    st.markdown("---")
    st.warning(
        "⚠️ Esto es solo el **IVA Generado** (el que cobraste en tus órdenes). Para la declaración "
        "completa también necesitas el **IVA Descontable** de tus compras a proveedores — MyTaller "
        "todavía no registra el IVA pagado en tus entradas de inventario o repuestos comprados, así "
        "que debes sumarlo aparte de tus facturas de compra. El valor a pagar (o el saldo a favor) "
        "es IVA Generado menos IVA Descontable."
    )
