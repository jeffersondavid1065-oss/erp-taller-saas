import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion
from queries import (
    obtener_categorias_gasto,
    obtener_gastos_filtrado,
    obtener_gastos_por_categoria,
    obtener_metricas_financieras,
    invalidar_cache_gastos,
)

st.set_page_config(page_title="Gastos y Análisis Financiero", layout="wide")

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
    </style>
""", unsafe_allow_html=True)

# Autenticación
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None, "email": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

st.title("Gastos y Análisis Financiero")
st.markdown(f"Control de gastos operacionales para: **{nombre_taller}**")
st.markdown("---")

# Crear categorías predefinidas si no existen
@st.cache_data(ttl=3600)
def inicializar_categorias_predefinidas(uid):
    with engine.begin() as conn:
        # Verificar si ya existen categorías para este usuario
        existe = conn.execute(text("SELECT COUNT(*) FROM Categorias_Gasto WHERE usuario_id = :uid"), {"uid": uid}).scalar()
        if existe == 0:
            categorias_default = [
                ("Nómina Mecánicos", "Gastos de personal"),
                ("Arriendo/Local", "Renta del local del taller"),
                ("Servicios", "Agua, luz, teléfono, internet"),
                ("Repuestos/Insumos", "Compra de materiales"),
                ("Combustible/Transporte", "Gasolina y transporte"),
                ("Herramientas", "Compra o mantenimiento de herramientas"),
                ("Mantenimiento Equipos", "Reparación de maquinaria"),
                ("Impuestos/Licencias", "Pagos tributarios"),
                ("Seguros", "Pólizas de seguro"),
                ("Otros", "Gastos varios"),
            ]
            for nombre, desc in categorias_default:
                conn.execute(
                    text("INSERT INTO Categorias_Gasto (usuario_id, nombre, descripcion, tipo) VALUES (:uid, :nom, :desc, 'Variable')"),
                    {"uid": uid, "nom": nombre, "desc": desc}
                )
    return True

inicializar_categorias_predefinidas(user_id)

tab_registrar, tab_historial, tab_analisis = st.tabs(["Registrar Gasto", "Historial de Gastos", "Análisis Financiero"])

# ==========================================
# TAB 1: REGISTRAR GASTO
# ==========================================
with tab_registrar:
    categorias = obtener_categorias_gasto(user_id)
    if categorias:
        dict_categorias = {c[1]: c[0] for c in categorias}
        opciones_categorias = list(dict_categorias.keys())

        with st.form("form_nuevo_gasto", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                categoria_sel = st.selectbox("Categoría de Gasto", options=opciones_categorias)
                descripcion = st.text_input("Descripción del gasto")
                monto = st.number_input("Monto ($)", min_value=0.0, step=1000.0)
            with col2:
                fecha_gasto = st.date_input("Fecha del gasto", value=datetime.today())
                tipo_gasto = st.selectbox("Tipo", ["Variable", "Fijo"])

            st.markdown("")
            if st.form_submit_button("Guardar Gasto", type="primary"):
                if descripcion and monto > 0 and categoria_sel:
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    INSERT INTO Gastos (usuario_id, categoria_id, descripcion, monto, fecha, tipo)
                                    VALUES (:uid, :cat_id, :desc, :monto, :fecha, :tipo)
                                """),
                                {
                                    "uid": user_id,
                                    "cat_id": dict_categorias[categoria_sel],
                                    "desc": descripcion,
                                    "monto": float(monto),
                                    "fecha": fecha_gasto.strftime('%Y-%m-%d'),
                                    "tipo": tipo_gasto
                                }
                            )
                        invalidar_cache_gastos()
                        st.success(f"Gasto de {formato_cop(monto)} registrado en {categoria_sel}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")
                else:
                    st.warning("Completa todos los campos obligatorios.")
    else:
        st.info("Inicializando categorías de gasto...")
        st.rerun()

# ==========================================
# TAB 2: HISTORIAL DE GASTOS
# ==========================================
with tab_historial:
    st.subheader("Historial de Gastos Registrados")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        hoy = datetime.today()
        hace_30 = hoy - timedelta(days=30)
        fechas = st.date_input("Rango de fechas", [hace_30, hoy])
    with col_f2:
        categorias = obtener_categorias_gasto(user_id)
        dict_categorias_filtro = {c[1]: c[0] for c in categorias}
        filtro_categoria = st.selectbox("Filtrar por categoría (opcional)", ["-- Todas --"] + list(dict_categorias_filtro.keys()))
    with col_f3:
        st.write("")  # Espaciador

    if len(fechas) == 2:
        fecha_ini, fecha_fin = fechas
        categoria_id_filtro = None if filtro_categoria == "-- Todas --" else dict_categorias_filtro[filtro_categoria]

        df_gastos = obtener_gastos_filtrado(user_id, fecha_ini, fecha_fin, categoria_id_filtro)

        if not df_gastos.empty:
            total_periodo = df_gastos['monto'].sum()
            st.success(f"Total gastos en el período: {formato_cop(total_periodo)}")

            df_mostrar = df_gastos[['categoria', 'descripcion', 'monto', 'fecha', 'tipo']].copy()
            df_mostrar.columns = ['Categoría', 'Descripción', 'Monto ($)', 'Fecha', 'Tipo']

            st.dataframe(
                df_mostrar.style.format({'Monto ($)': lambda x: formato_cop(x)}),
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                # Gastos fijos vs variables
                df_fijos_vars = df_gastos.groupby('tipo')['monto'].sum().reset_index()
                st.markdown("**Gastos Fijos vs Variables:**")
                for idx, row in df_fijos_vars.iterrows():
                    st.write(f"• {row['tipo']}: {formato_cop(row['monto'])}")
            with col_exp2:
                # Top 3 categorías
                df_top_cat = df_gastos.groupby('categoria')['monto'].sum().nlargest(3).reset_index()
                st.markdown("**Top 3 Categorías:**")
                for idx, row in df_top_cat.iterrows():
                    st.write(f"• {row['categoria']}: {formato_cop(row['monto'])}")
        else:
            st.info("No hay gastos registrados en este período.")

# ==========================================
# TAB 3: ANÁLISIS FINANCIERO
# ==========================================
with tab_analisis:
    st.subheader("Dashboard Financiero Mensual")

    col_mes1, col_mes2 = st.columns(2)
    with col_mes1:
        mes_sel = st.selectbox("Mes", range(1, 13), format_func=lambda m: ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][m-1])
    with col_mes2:
        año_sel = st.number_input("Año", value=datetime.today().year, min_value=2020)

    # Nota: obtener_metricas_financieras necesita una query simplificada
    # Por ahora, calcular localmente desde los gastos
    fecha_inicio_mes = datetime(año_sel, mes_sel, 1).date()
    if mes_sel == 12:
        fecha_fin_mes = datetime(año_sel + 1, 1, 1).date() - timedelta(days=1)
    else:
        fecha_fin_mes = datetime(año_sel, mes_sel + 1, 1).date() - timedelta(days=1)

    df_gastos_mes = obtener_gastos_filtrado(user_id, fecha_inicio_mes, fecha_fin_mes)
    gastos_totales = df_gastos_mes['monto'].sum() if not df_gastos_mes.empty else 0

    # Calcular ingresos del mes (órdenes facturadas)
    with engine.connect() as conn:
        ingresos_result = conn.execute(
            text("""
                SELECT COALESCE(SUM(d.precio_venta), 0) as total
                FROM Detalles_Orden d
                JOIN Hojas_Trabajo h ON d.hoja_id = h.id
                WHERE h.usuario_id = :uid AND h.estado = 'Facturado'
                AND EXTRACT(YEAR FROM h.fecha_ingreso) = :año
                AND EXTRACT(MONTH FROM h.fecha_ingreso) = :mes
            """),
            {"uid": user_id, "año": año_sel, "mes": mes_sel}
        ).scalar()
    ingresos_totales = float(ingresos_result) if ingresos_result else 0

    margen_neto = ingresos_totales - gastos_totales

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Ingresos", formato_cop(ingresos_totales))
    col_m2.metric("Gastos", formato_cop(gastos_totales), delta=f"-{formato_cop(gastos_totales)}")
    col_m3.metric("Margen Neto", formato_cop(margen_neto), delta_color="inverse" if margen_neto < 0 else "normal")
    if ingresos_totales > 0:
        pct_margen = (margen_neto / ingresos_totales) * 100
        col_m4.metric("% Margen", f"{pct_margen:.1f}%")

    st.markdown("---")

    col_graf1, col_graf2 = st.columns(2)

    with col_graf1:
        st.markdown("**Gastos por Categoría**")
        df_por_cat = obtener_gastos_por_categoria(user_id, fecha_inicio_mes, fecha_fin_mes)
        if not df_por_cat.empty:
            st.bar_chart(df_por_cat.set_index('nombre')['total'], height=300)
        else:
            st.info("Sin gastos en este mes.")

    with col_graf2:
        st.markdown("**Proporción Gastos Fijos vs Variables**")
        if not df_gastos_mes.empty:
            df_fijos_vars_pie = df_gastos_mes.groupby('tipo')['monto'].sum().reset_index()
            if not df_fijos_vars_pie.empty:
                st.bar_chart(df_fijos_vars_pie.set_index('tipo')['monto'], height=300)
            else:
                st.info("Sin gastos en este mes.")
        else:
            st.info("Sin gastos en este mes.")

    st.markdown("---")
    st.markdown("**Resumen Detallado**")
    
    col_res1, col_res2, col_res3 = st.columns(3)
    with col_res1:
        st.write("**Ingresos Facturados:**")
        st.write(f"`{formato_cop(ingresos_totales)}`")
    with col_res2:
        st.write("**Total Gastos:**")
        st.write(f"`{formato_cop(gastos_totales)}`")
    with col_res3:
        st.write("**Rentabilidad (Margen Neto):**")
        color = "🔴" if margen_neto < 0 else "🟢"
        st.write(f"{color} `{formato_cop(margen_neto)}`")
