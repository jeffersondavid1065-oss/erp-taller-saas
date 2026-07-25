import streamlit as st
import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Administración - MyTaller", layout="wide")

# Ocultar barra superior predeterminada
st.markdown("""
    <style>
    [data-testid="stHeader"] {
        display: none !important;
    }
    </style>
""", unsafe_allow_html=True)

# Validación de seguridad
CORREO_ADMIN = "jefferson.david1065@gmail.com"

if not st.session_state.get('user_logged', False):
    st.warning("Debe iniciar sesión para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

# Verificación de credenciales de administrador
with engine.connect() as conn:
    res = conn.execute(text("SELECT email FROM Usuarios WHERE id = :uid"), {"uid": user_id}).fetchone()
    email_actual = res[0] if res else ""

if email_actual != CORREO_ADMIN:
    st.error("Acceso denegado. Esta sección es de uso exclusivo para la administración del sistema.")
    st.stop()

# ==========================================
# PANEL DE ADMINISTRACIÓN
# ==========================================
st.title("Panel de Control de Suscripciones")
st.markdown("Módulo para la administración de usuarios, activación de cuentas y gestión de fechas de corte.")
st.markdown("---")

# Consultar base de datos de usuarios
with engine.connect() as conn:
    df_talleres = pd.read_sql_query(
        text("SELECT id, nombre_taller, nombre_dueno, email, activo, fecha_pago_limite FROM Usuarios ORDER BY id DESC"),
        con=conn
    )

if not df_talleres.empty:
    st.subheader("Directorio de Talleres Registrados")
    
    # Visualización de datos
    st.dataframe(df_talleres, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.subheader("Gestión de Suscripciones y Accesos")
    
    dict_talleres = {f"ID {row['id']} - {row['nombre_taller']} ({row['email']})": row['id'] for index, row in df_talleres.iterrows()}
    
    taller_sel_str = st.selectbox("Seleccione el taller a gestionar:", options=list(dict_talleres.keys()))
    
    if taller_sel_str:
        taller_id_activo = dict_talleres[taller_sel_str]
        taller_row = df_talleres[df_talleres['id'] == taller_id_activo].iloc[0]
        
        col1, col2 = st.columns(2)
        with col1:
            st.info(
                f"**Propietario:** {taller_row['nombre_dueno']}\n\n"
                f"**Estado de la cuenta:** {'Activa' if taller_row['activo'] else 'Inactiva'}\n\n"
                f"**Fecha de corte actual:** {taller_row['fecha_pago_limite'] or 'Sin fecha asignada'}"
            )
        
        with col2:
            st.markdown("### Acciones Disponibles")
            
            if st.button("Extender 30 días", type="primary", use_container_width=True):
                nueva_fecha = date.today() + timedelta(days=30)
                try:
                    with engine.begin() as conn_upd:
                        conn_upd.execute(
                            text("UPDATE Usuarios SET fecha_pago_limite = :f_lim, activo = TRUE WHERE id = :id"),
                            {"f_lim": nueva_fecha, "id": taller_id_activo}
                        )
                    st.success(f"Suscripción actualizada exitosamente. Nueva fecha de corte: {nueva_fecha}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error en la actualización de base de datos: {e}")
            
            if st.button("Suspender Acceso", use_container_width=True):
                fecha_vencida = date.today() - timedelta(days=1) 
                try:
                    with engine.begin() as conn_bloq:
                        conn_bloq.execute(
                            text("UPDATE Usuarios SET fecha_pago_limite = :f_lim WHERE id = :id"),
                            {"f_lim": fecha_vencida, "id": taller_id_activo}
                        )
                    st.warning(f"El acceso para el taller '{taller_row['nombre_taller']}' ha sido suspendido.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al procesar la suspensión: {e}")
else:
    st.info("Actualmente no existen talleres registrados en el sistema.")
