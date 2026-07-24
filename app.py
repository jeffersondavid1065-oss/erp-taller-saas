import streamlit as st
import pandas as pd
import hashlib
from sqlalchemy import text
from db import init_db, obtener_conexion

st.set_page_config(
    page_title="ERP Taller Automotriz - SaaS", 
    page_icon="⚙️", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inicializar Base de Datos
init_db()

def hacer_hash(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

# ==========================================
# GESTIÓN DE SESIÓN
# ==========================================
if 'user_logged' not in st.session_state:
    st.session_state.user_logged = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'nombre_taller' not in st.session_state:
    st.session_state.nombre_taller = ""

# ==========================================
# INTERFAZ DE LOGIN Y REGISTRO
# ==========================================
if not st.session_state.user_logged:
    st.title("⚙️ Sistema ERP Cloud para Talleres Automotrices")
    st.markdown("### La solución definitiva para administrar tu taller, inventarios y nóminas.")
    st.markdown("---")
    
    col_login, col_reg = st.columns(2)
    
    with col_login:
        st.subheader("🔐 Iniciar Sesión")
        with st.form("form_login"):
            email_log = st.text_input("Correo Electrónico")
            pass_log = st.text_input("Contraseña", type="password")
            btn_login = st.form_submit_button("Ingresar a mi Taller", type="primary")
            
            if btn_login:
                if email_log and pass_log:
                    engine = obtener_conexion()
                    query = "SELECT id, nombre_taller, password, estado_suscripcion FROM Usuarios WHERE email = :email"
                    
                    with engine.connect() as conn:
                        user = conn.execute(text(query), {"email": email_log}).fetchone()
                    
                    if user:
                        user_id, taller_name, hashed_pass, estado_sub = user
                        if hashed_pass == hacer_hash(pass_log):
                            if estado_sub == 'Activo':
                                st.session_state.user_logged = True
                                st.session_state.user_id = user_id
                                st.session_state.nombre_taller = taller_name
                                st.success(f"¡Bienvenido de nuevo, {taller_name}!")
                                st.rerun()
                            else:
                                st.error("❌ Tu suscripción está inactiva.")
                        else:
                            st.error("❌ Contraseña incorrecta.")
                    else:
                        st.error("❌ Este correo no está registrado.")
                else:
                    st.warning("Completa todos los campos.")

    with col_reg:
        st.subheader("🚀 Registrar Nuevo Taller (Software SaaS)")
        st.markdown("¿Eres dueño de un taller? Regístrate aquí.")
        with st.form("form_registro_taller"):
            reg_taller = st.text_input("Nombre del Taller Mecánico")
            reg_dueno = st.text_input("Tu Nombre Completo (Propietario)")
            reg_email = st.text_input("Correo Electrónico Comercial")
            reg_pass = st.text_input("Crea una Contraseña", type="password")
            btn_reg = st.form_submit_button("Crear Cuenta y Activar Taller")
            
            if btn_reg:
                if reg_taller and reg_dueno and reg_email and reg_pass:
                    engine = obtener_conexion()
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text('''
                                    INSERT INTO Usuarios (nombre_taller, nombre_dueno, email, password) 
                                    VALUES (:taller, :dueno, :email, :pass)
                                '''),
                                {
                                    "taller": reg_taller, 
                                    "dueno": reg_dueno, 
                                    "email": reg_email, 
                                    "pass": hacer_hash(reg_pass)
                                }
                            )
                        st.success("✅ ¡Taller registrado con éxito! Ya puedes iniciar sesión.")
                    except Exception as e:
                        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                            st.error("❌ Error: Este correo electrónico ya está registrado.")
                        else:
                            st.error(f"❌ Error al registrar: {e}")
                else:
                    st.warning("Por favor completa todos los campos.")

# ==========================================
# PANEL DIRECTIVO (SESIÓN ACTIVA)
# ==========================================
else:
    st.sidebar.success(f"🏢 Taller: {st.session_state.nombre_taller}")
    
    # Botón limpio para cerrar sesión sin errores
    if st.sidebar.button("🚪 Cerrar Sesión"):
        st.session_state.user_logged = False
        st.session_state.user_id = None
        st.session_state.nombre_taller = ""
        st.rerun()

    st.title(f"⚙️ Panel Directivo - {st.session_state.nombre_taller}")
    st.markdown("Resumen operativo en tiempo real de tu taller mecánico.")
    st.markdown("---")

    engine = obtener_conexion()
    try:
        df_ordenes = pd.read_sql_query(
            text("SELECT estado FROM Hojas_Trabajo WHERE usuario_id = :uid"), 
            con=engine, 
            params={"uid": st.session_state.user_id}
        )
        df_detalles = pd.read_sql_query(
            text('''
                SELECT d.precio_venta FROM Detalles_Orden d
                JOIN Hojas_Trabajo h ON d.hoja_id = h.id
                WHERE h.usuario_id = :uid
            '''), 
            con=engine, 
            params={"uid": st.session_state.user_id}
        )
        
        total_ordenes = len(df_ordenes)
        listas_facturar = len(df_ordenes[df_ordenes['estado'] == 'Listo para facturar']) if not df_ordenes.empty else 0
        total_facturado = df_detalles['precio_venta'].sum() if not df_detalles.empty else 0
    except Exception:
        total_ordenes, listas_facturar, total_facturado = 0, 0, 0

    col1, col2, col3 = st.columns(3)
    col1.metric("🚗 Total Órdenes del Taller", total_ordenes)
    col2.metric("✅ Listas para Facturar", listas_facturar)
    col3.metric("💰 Facturación Acumulada", formato_cop(total_facturado))

    st.markdown("---")
    st.subheader("⚡ Accesos Directos a los Módulos")
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.info("🚗 **Recepción**\n\nIngresa vehículos y asigna trabajos.")
    with c2:
        st.info("🚥 **Kanban**\n\nSupervisa el patio de tu taller.")
    with c3:
        st.info("📑 **Expediente**\n\nFactura y edita órdenes semanales.")
    with c4:
        st.info("💰 **Nómina**\n\nLiquida comisiones a tus mecánicos.")
