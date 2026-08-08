import streamlit as st
from datetime import datetime, timedelta
from queries import obtener_resumen_financiero_periodo, obtener_iva_por_tasa_periodo, obtener_gastos_por_categoria

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

tab_resumen, tab_iva = st.tabs(["Resumen del Negocio", "Declarar IVA"])

# ==========================================
# TAB 1: RESUMEN DEL NEGOCIO
# ==========================================
with tab_resumen:
    resumen = obtener_resumen_financiero_periodo(user_id, fecha_inicio, fecha_fin)

    st.caption(
        "Los ingresos, la utilidad bruta y la utilidad neta ya están calculados **sin el IVA cobrado**: "
        "ese IVA no es ganancia del taller, es dinero que hay que entregarle a la DIAN "
        "(revisa cuánto en la pestaña 'Declarar IVA')."
    )

    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric("Órdenes Facturadas", resumen["num_ordenes"])
    ticket_promedio = resumen["ingresos"] / resumen["num_ordenes"] if resumen["num_ordenes"] else 0
    col_r2.metric("Ticket Promedio", formato_cop(ticket_promedio))
    col_r3.metric("IVA Recaudado (no es ingreso)", formato_cop(resumen["iva_recaudado"]))

    st.markdown("---")
    st.markdown("**De ingresos a utilidad neta:**")

    col_u1, col_u2, col_u3, col_u4, col_u5 = st.columns(5)
    col_u1.metric("Ingresos", formato_cop(resumen["ingresos"]))
    col_u2.metric("Costo Directo", formato_cop(resumen["costo_directo"]), delta=f"-{formato_cop(resumen['costo_directo'])}")
    col_u3.metric("Utilidad Bruta", formato_cop(resumen["utilidad_bruta"]))
    col_u4.metric("Gastos Operativos", formato_cop(resumen["gastos"]), delta=f"-{formato_cop(resumen['gastos'])}")
    col_u5.metric(
        "Utilidad Neta", formato_cop(resumen["utilidad_neta"]),
        delta_color="inverse" if resumen["utilidad_neta"] < 0 else "normal"
    )

    if resumen["ingresos"] > 0:
        pct_utilidad = (resumen["utilidad_neta"] / resumen["ingresos"]) * 100
        st.caption(f"Margen neto sobre ingresos: **{pct_utilidad:.1f}%**")

    st.markdown("---")
    st.markdown("**Gastos por categoría en el período:**")
    df_gastos_cat = obtener_gastos_por_categoria(user_id, fecha_inicio, fecha_fin)
    if not df_gastos_cat.empty:
        st.bar_chart(df_gastos_cat.set_index('nombre')['total'], height=300)
    else:
        st.info("No hay gastos registrados en este período.")

# ==========================================
# TAB 2: DECLARAR IVA
# ==========================================
with tab_iva:
    st.subheader("IVA a Declarar")
    st.caption(
        "Desglose del IVA generado en el período, por tasa - es el mismo dato que necesitas "
        "para la casilla de IVA Generado de tu declaración de IVA (Formulario 300). "
        "Este dinero ya fue cobrado a tus clientes, pero no es utilidad del taller: hay que "
        "entregárselo a la DIAN."
    )

    df_iva = obtener_iva_por_tasa_periodo(user_id, fecha_inicio, fecha_fin)

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
