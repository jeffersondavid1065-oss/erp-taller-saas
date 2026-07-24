import streamlit as st
import sqlite3
import os

st.set_page_config(page_title="Tablero Kanban", page_icon="🚥", layout="wide")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

user_id = st.session_state.user_id

st.title("🚥 Tablero de Control Operativo")
st.markdown(f"Patio de vehículos para: **{st.session_state.nombre_taller}**")
st.markdown("---")

def obtener_vehiculos():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 🌟 FILTRAMOS ESTRICTAMENTE POR EL ID DEL TALLER ACTUAL
    cursor.execute('''
        SELECT h.id, h.placa, e.razon_social, h.estado 
        FROM Hojas_Trabajo h
        JOIN Empresas_Clientes e ON h.empresa_id = e.id
        WHERE h.usuario_id = ?
    ''', (user_id,))
    datos = cursor.fetchall()
    conn.close()
    return datos

try:
    vehiculos = obtener_vehiculos()
except Exception:
    vehiculos = []

col1, col2, col3, col4, col5 = st.columns(5)

def dibujar_tarjetas(columna, titulo, estado_filtro, emoji):
    with columna:
        st.subheader(f"{emoji} {titulo}")
        st.markdown("---")
        contador = 0
        
        for v in vehiculos:
            orden_id, placa, empresa, estado_actual = v
            if estado_actual == estado_filtro:
                with st.container(border=True):
                    st.markdown(f"**Orden #{orden_id} | Placa: {placa}**")
                    st.caption(f"🏢 {empresa}")
                contador += 1
                
        if contador == 0:
            st.info("Vacío")

dibujar_tarjetas(col1, "Cotizar", "Cotizar", "📝")
dibujar_tarjetas(col2, "En Revisión", "En revisión", "📋")
dibujar_tarjetas(col3, "Esperando Repuestos", "Esperando repuestos", "📦")
dibujar_tarjetas(col4, "En Reparación", "En reparación", "🔧")
dibujar_tarjetas(col5, "Listo para Facturar", "Listo para facturar", "✅")

st.markdown("---")
if st.button("🔄 Actualizar Tablero"):
    st.rerun()