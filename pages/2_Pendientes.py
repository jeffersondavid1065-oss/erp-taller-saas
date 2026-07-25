import streamlit as st
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Tablero de Control", layout="wide")

# ==========================================
# ESTILOS CSS: OCULTAR BARRA, ANIMACIONES Y COLORES KANBAN
# ==========================================
st.markdown("""
    <style>
    /* 1. Ocultar toda la esquina superior derecha (Fork, GitHub, Menu) */
    [data-testid="stHeader"] {
        display: none !important;
    }

    /* 2. Definir la animación de entrada */
    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    
    [data-testid="stAppViewBlockContainer"] {
        animation: fade-in-up 0.6s ease-out;
    }
    
    div[data-testid="stVerticalBlock"] > div {
        animation: fade-in-up 0.5s ease-out;
    }

    /* 3. Estilos personalizados para los fondos pastel de las columnas */
    .kanban-column {
        padding: 16px;
        border-radius: 12px;
        margin-bottom: 10px;
        border: 1px solid rgba(0, 0, 0, 0.04);
    }
    .bg-cotizar { background-color: #f0f4f8; }
    .bg-revision { background-color: #fcf8e8; }
    .bg-repuestos { background-color: #fbf1ed; }
    .bg-reparacion { background-color: #f0ebf8; }
    .bg-facturar { background-color: #edf7ed; }
    </style>
""", unsafe_allow_html=True)

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

st.title("Tablero de Control Operativo")
st.markdown(f"Patio de vehículos para: **{st.session_state.nombre_taller}**")
st.markdown("---")

def obtener_vehiculos():
    with engine.connect() as conn:
        query = text('''
            SELECT h.id, h.placa, e.razon_social, h.estado 
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            WHERE h.usuario_id = :uid
        ''')
        datos = conn.execute(query, {"uid": user_id}).fetchall()
    return datos

try:
    vehiculos = obtener_vehiculos()
except Exception as e:
    vehiculos = []
    st.error(f"Error al conectar con la base de datos: {e}")

col1, col2, col3, col4, col5 = st.columns(5)

def dibujar_columna(columna, titulo, estado_filtro, clase_css):
    with columna:
        st.markdown(f"""
            <div class="kanban-column {clase_css}">
                <h4 style="margin-top: 0; font-weight: 600; color: #31333F; font-size: 1.1rem;">{titulo}</h4>
                <hr style="margin: 8px 0; border: none; border-top: 1px solid rgba(0,0,0,0.08);">
        """, unsafe_allow_html=True)
        
        contador = 0
        for v in vehiculos:
            orden_id, placa, empresa, estado_actual = v
            if estado_actual == estado_filtro:
                with st.container(border=True):
                    st.markdown(f"**Orden #{orden_id}**")
                    st.markdown(f"Placa: **{placa}**")
                    st.caption(f"Empresa: {empresa}")
                contador += 1
                
        if contador == 0:
            st.caption("Vacío")
            
        st.markdown("</div>", unsafe_allow_html=True)

dibujar_columna(col1, "Cotizar", "Cotizar", "bg-cotizar")
dibujar_columna(col2, "En Revisión", "En revisión", "bg-revision")
dibujar_columna(col3, "Esperando Repuestos", "Esperando repuestos", "bg-repuestos")
dibujar_columna(col4, "En Reparación", "En reparación", "bg-reparacion")
dibujar_columna(col5, "Listo para Facturar", "Listo para facturar", "bg-facturar")

st.markdown("---")
if st.button("Actualizar Tablero"):
    st.rerun()
