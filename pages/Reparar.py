import streamlit as st
from sqlalchemy import text
from db import obtener_conexion

st.title("🛠️ Reparación Automática de Base de Datos")
st.write("Presiona el botón para inyectar las nuevas columnas en la nube.")

if st.button("Arreglar Base de Datos", type="primary"):
    engine = obtener_conexion()
    try:
        with engine.begin() as conn:
            # Agregamos las columnas directamente mediante código
            conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS codigo_verificacion TEXT;"))
            conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS fecha_pago_limite DATE;"))
        
        st.success("✅ ¡Éxito! Las columnas fueron agregadas. Ya puedes volver a la página principal e iniciar sesión sin errores.")
    except Exception as e:
        st.error(f"Ocurrió un error: {e}")
