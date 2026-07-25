import streamlit as st
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Tablero de Control", layout="wide")

# Validacion de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesion en la pagina principal para acceder a este modulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

st.title("Tablero de Control Operativo")
st.markdown(f"Patio de vehiculos para: **{st.session_state.nombre_taller}**")
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

def dibujar_tarjetas(columna, titulo, estado_filtro):
    with columna:
        st.subheader(titulo)
        st.markdown("---")
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
            st.info("Vacio")

dibujar_tarjetas(col1, "Cotizar", "Cotizar")
dibujar_tarjetas(col2, "En Revision", "En revision")
dibujar_tarjetas(col3, "Esperando Repuestos", "Esperando repuestos")
dibujar_tarjetas(col4, "En Reparacion", "En reparacion")
dibujar_tarjetas(col5, "Listo para Facturar", "Listo para facturar")

st.markdown("---")
if st.button("Actualizar Tablero"):
    st.rerun()
