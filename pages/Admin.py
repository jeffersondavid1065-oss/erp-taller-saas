import streamlit as st
import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text
from db import obtener_conexion, mensaje_error_amigable
from queries import establecer_fe_habilitada

# ==========================================
# ESTILOS CSS: MÁSCARA DERECHA Y ANIMACIONES
# ==========================================
_mostrar_animacion_pagina = st.session_state.get("_ultima_pagina_animada") != "admin"
st.session_state["_ultima_pagina_animada"] = "admin"
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
        background-color: #0e1117 !important;
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
# AUTENTICACIÓN Y VERIFICACIÓN DE ADMINISTRADOR
# --------------------------------------------------------------------------------
# El correo de administrador debería idealmente vivir en st.secrets en vez de
# quedar escrito en el código fuente (visible en el repo de GitHub). Se deja
# aquí funcional por ahora; ver nota al final sobre cómo moverlo a secrets.
CORREO_ADMIN = "jefferson.david1065@gmail.com"

if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None, "email": None}

if not st.session_state.auth["logged"]:
    st.warning("Debe iniciar sesión para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]

# El email ya quedó guardado en session_state al hacer login (ver app.py),
# así que no hace falta una consulta a la base de datos solo para verificar
# quién es administrador en cada carga de esta página.
email_actual = st.session_state.auth.get("email")

if email_actual != CORREO_ADMIN:
    st.error("Acceso denegado. Esta sección es de uso exclusivo para la administración del sistema.")
    st.stop()

# ==========================================
# CONSULTA CACHEADA: LISTA DE TALLERES
# ==========================================
@st.cache_data(ttl=30)
def obtener_talleres():
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("""
                SELECT id, nombre_taller, nombre_dueno, email, activo, fecha_pago_limite,
                       COALESCE(fe_habilitada, FALSE) as fe_habilitada
                FROM Usuarios ORDER BY id DESC
            """),
            con=conn
        )

# ==========================================
# PANEL DE ADMINISTRACIÓN
# ==========================================
st.title("Panel de Control de Suscripciones")
st.markdown("Módulo para la administración de usuarios, activación de cuentas y gestión de fechas de corte.")
st.markdown("---")

df_talleres = obtener_talleres()

if not df_talleres.empty:
    st.subheader("Directorio de Talleres Registrados")
    
    st.dataframe(df_talleres, width='stretch', hide_index=True)
    
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
            
            if st.button("Extender 30 días", type="primary", width='stretch'):
                nueva_fecha = date.today() + timedelta(days=30)
                try:
                    with engine.begin() as conn_upd:
                        conn_upd.execute(
                            text("UPDATE Usuarios SET fecha_pago_limite = :f_lim, activo = TRUE WHERE id = :id"),
                            {"f_lim": nueva_fecha, "id": taller_id_activo}
                        )
                    obtener_talleres.clear()
                    st.success(f"Suscripción actualizada exitosamente. Nueva fecha de corte: {nueva_fecha}")
                    st.rerun()
                except Exception as e:
                    st.error(mensaje_error_amigable(e, "extender la suscripción"))

            if st.button("Suspender Acceso", width='stretch'):
                st.session_state[f"confirmar_suspender_{taller_id_activo}"] = True

            if st.session_state.get(f"confirmar_suspender_{taller_id_activo}", False):
                st.warning(f"¿Suspender el acceso de **{taller_row['nombre_taller']}**? El taller no podrá usar el sistema hasta que le extiendas la suscripción de nuevo.")
                col_sa1, col_sa2 = st.columns(2)
                with col_sa1:
                    if st.button("Sí, suspender", type="primary", width='stretch', key=f"yes_susp_{taller_id_activo}"):
                        fecha_vencida = date.today() - timedelta(days=1)
                        try:
                            with engine.begin() as conn_bloq:
                                conn_bloq.execute(
                                    text("UPDATE Usuarios SET fecha_pago_limite = :f_lim WHERE id = :id"),
                                    {"f_lim": fecha_vencida, "id": taller_id_activo}
                                )
                            obtener_talleres.clear()
                            st.session_state[f"confirmar_suspender_{taller_id_activo}"] = False
                            st.warning(f"El acceso para el taller '{taller_row['nombre_taller']}' ha sido suspendido.")
                            st.rerun()
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "suspender el acceso"))
                with col_sa2:
                    if st.button("Cancelar", width='stretch', key=f"no_susp_{taller_id_activo}"):
                        st.session_state[f"confirmar_suspender_{taller_id_activo}"] = False
                        st.rerun()

        st.markdown("---")
        st.markdown("### Facturación Electrónica")
        st.caption(
            "Controla qué talleres pueden ver y usar la integración de facturación electrónica "
            "(configurar credenciales, emitir facturas/notas crédito ante la DIAN). "
            "Nuevos talleres empiezan sin acceso."
        )
        fe_activa = bool(taller_row['fe_habilitada'])
        st.write(f"Estado actual: {'Habilitada' if fe_activa else 'Deshabilitada'}")
        col_fe1, col_fe2 = st.columns(2)
        with col_fe1:
            if st.button("Habilitar FE", type="primary", width='stretch', disabled=fe_activa):
                establecer_fe_habilitada(taller_id_activo, True)
                obtener_talleres.clear()
                st.success(f"Facturación Electrónica habilitada para '{taller_row['nombre_taller']}'.")
                st.rerun()
        with col_fe2:
            if st.button("Deshabilitar FE", width='stretch', disabled=not fe_activa):
                establecer_fe_habilitada(taller_id_activo, False)
                obtener_talleres.clear()
                st.warning(f"Facturación Electrónica deshabilitada para '{taller_row['nombre_taller']}'.")
                st.rerun()
else:
    st.info("Actualmente no existen talleres registrados en el sistema.")
