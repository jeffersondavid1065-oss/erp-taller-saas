import streamlit as st
import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Panel de Administración - MyTaller", layout="wide")

# Ocultar barra superior predeterminada
st.markdown("""
    <style>
    [data-testid="stHeader"] {
        display: none !important;
    }
    </style>
""", unsafe_allow_html=True)

# Validación de seguridad: Solo tú puedes entrar a este panel
CORREO_ADMIN = "jefferson.david1065@gmail.com"  # <--- CAMBIA ESTE CORREO POR EL TUYO

if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesión.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

# Verificamos si el usuario actual es el administrador
with engine.connect() as conn:
    res = conn.execute(text("SELECT email FROM Usuarios WHERE id = :uid"), {"uid": user_id}).fetchone()
    email_actual = res[0] if res else ""

if email_actual != CORREO_ADMIN:
    st.error("⛔ Acceso denegado. Esta sección es exclusiva para el administrador del sistema.")
    st.stop()

# ==========================================
# PANEL DE ADMINISTRACIÓN DE TALLERES
# ==========================================
st.title("🛠️ Panel Maestro - Control de Suscripciones")
st.markdown("Administra los talleres registrados, activa cuentas o extiende las fechas de pago mensual.")
st.markdown("---")

# Consultar todos los talleres registrados
with engine.connect() as conn:
    df_talleres = pd.read_sql_query(
        text("SELECT id, nombre_taller, nombre_dueno, email, activo, fecha_pago_limite FROM Usuarios ORDER BY id DESC"),
        con=conn
    )

if not df_talleres.empty:
    st.subheader("Talleres Registrados en el Sistema")
    
    # Mostrar tabla limpia
    st.dataframe(df_talleres, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.subheader("⚙️ Extender Suscripción o Activar Taller")
    
    # Diccionario para seleccionar el taller a modificar
    dict_talleres = {f"ID {row['id']} - {row['nombre_taller']} ({row['email']})": row['id'] for index, row in df_talleres.iterrows()}
    
    taller_sel_str = st.selectbox("Selecciona el taller a gestionar:", options=list(dict_talleres.keys()))
    
    if taller_sel_str:
        taller_id_activo = dict_talleres[taller_sel_str]
        taller_row = df_talleres[df_talleres['id'] == taller_id_activo].iloc[0]
        
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Propietario:** {taller_row['nombre_dueno']}\n\n**Estado Actual Activo:** {taller_row['activo']}\n\n**Fecha Límite Actual:** {taller_row['fecha_pago_limite'] or 'Sin fecha asignada'}")
        
        with col2:
            st.markdown("### Acciones de Pago")
            # Botones para sumar 30 días a partir de hoy (o de la fecha límite actual)
            if st.button("➕ Extender 30 días de suscripción", type="primary", use_container_width=True):
                nueva_fecha = date.today() + timedelta(days=30)
                try:
                    with engine.begin() as conn_upd:
                        conn_upd.execute(
                            text("UPDATE Usuarios SET fecha_pago_limite = :f_lim, activo = TRUE WHERE id = :id"),
                            {"f_lim": nueva_fecha, "id": taller_id_activo}
                        )
                    st.success(f"¡Suscripción extendida con éxito hasta el {nueva_fecha} para {taller_row['nombre_taller']}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al actualizar: {e}")
            
            if st.button("🔒 Bloquear / Suspender Acceso", use_container_width=True):
                fecha_vencida = date.today() - timedelta(days=1) # Fecha en pasado para bloquearlo de inmediato
                try:
                    with engine.begin() as conn_bloq:
                        conn_bloq.execute(
                            text("UPDATE Usuarios SET fecha_pago_limite = :f_lim WHERE id = :id"),
                            {"f_lim": fecha_vencida, "id": taller_id_activo}
                        )
                    st.warning(f"El taller {taller_row['nombre_taller']} ha sido suspendido por falta de pago.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al suspender: {e}")
else:
    st.info("No hay talleres registrados todavía.")
