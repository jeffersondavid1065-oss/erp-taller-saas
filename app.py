import streamlit as st
from sqlalchemy import text
from db import obtener_conexion
import hashlib

st.set_page_config(page_title="Sistema ERP", layout="centered")

engine = obtener_conexion()

if 'user_logged' not in st.session_state:
    st.session_state.user_logged = False

if not st.session_state.user_logged:
    # Centramos el contenido principal con columnas
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<h2 style='text-align: center;'>MyTaller</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Plataforma de gestion para talleres automotrices</p>", unsafe_allow_html=True)
        st.markdown("---")
        
        # Tarjeta limpia de inicio de sesion
        with st.container(border=True):
            st.subheader("Iniciar Sesion")
            email_login = st.text_input("Correo Electronico", key="login_email")
            pass_login = st.text_input("Contrasena", type="password", key="login_pass")
            
            st.markdown("")
            if st.button("Ingresar", use_container_width=True, type="primary"):
                if email_login and pass_login:
                    pass_hash = hashlib.sha256(pass_login.encode()).hexdigest()
                    with engine.connect() as conn:
                        query = text("SELECT id, nombre_taller, password FROM Usuarios WHERE email = :email")
                        user = conn.execute(query, {"email": email_login}).fetchone()
                    
                    if user and user[2] == pass_hash:
                        st.session_state.user_logged = True
                        st.session_state.user_id = user[0]
                        st.session_state.nombre_taller = user[1]
                        st.rerun()
                    else:
                        st.error("Credenciales incorrectas.")
                else:
                    st.warning("Completa todos los campos.")
        
        st.markdown("")
        
        # Opcion de registro desplegable (minimalista)
        with st.expander("Registrar Nuevo Taller"):
            with st.form("form_registro"):
                taller_reg = st.text_input("Nombre del Taller")
                nombre_reg = st.text_input("Nombre del Propietario")
                email_reg = st.text_input("Correo Electronico Comercial")
                pass_reg = st.text_input("Contrasena", type="password")
                
                st.markdown("")
                btn_reg = st.form_submit_button("Crear Cuenta y Activar", use_container_width=True)
                if btn_reg:
                    if taller_reg and nombre_reg and email_reg and pass_reg:
                        pass_hash_reg = hashlib.sha256(pass_reg.encode()).hexdigest()
                        try:
                            with engine.begin() as conn_reg:
                                conn_reg.execute(
                                    text("""
                                        INSERT INTO Usuarios (nombre_taller, nombre_propietario, email, password)
                                        VALUES (:taller, :nombre, :email, :pass)
                                    """),
                                    {
                                        "taller": taller_reg,
                                        "nombre": nombre_reg,
                                        "email": email_reg,
                                        "pass": pass_hash_reg
                                    }
                                )
                            st.success("Cuenta creada con exito. Ya puedes iniciar sesion.")
                        except Exception as e:
                            st.error(f"Error al registrar: {e}")
                    else:
                        st.warning("Completa todos los campos para registrarte.")
else:
    st.title("Panel Principal")
    st.write(f"Bienvenido al sistema del taller: {st.session_state.get('nombre_taller', '')}")
    if st.button("Cerrar Sesion"):
        st.session_state.user_logged = False
        st.rerun()
