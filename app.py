import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion
import hashlib
from datetime import date

st.set_page_config(page_title="MyTaller", layout="wide")

# 1. ANIMACION DE ENTRADA Y CONTROL DINÁMICO DE LA BARRA LATERAL
if not st.session_state.get('user_logged', False):
    st.markdown("""
        <style>
        [data-testid="stHeader"] {
            display: none !important;
        }
        [data-testid="stSidebar"] {
            display: none !important;
        }
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
        </style>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
        <style>
        [data-testid="stHeader"] {
            display: none !important;
        }
        [data-testid="stSidebar"] {
            display: block !important;
        }
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
        </style>
    """, unsafe_allow_html=True)

engine = obtener_conexion()

if 'user_logged' not in st.session_state:
    st.session_state.user_logged = False

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

if not st.session_state.user_logged:
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
            <div style='text-align: center; margin-bottom: 25px;'>
                <h1 style='font-weight: 800; font-size: 2.5rem; letter-spacing: -1px; margin-bottom: 0;'>
                    My<span style='color: #FF4B4B;'>Taller</span>
                </h1>
                <p style='color: #64748b; font-size: 0.95rem; margin-top: 5px;'>
                    Gestión inteligente para talleres automotrices
                </p>
            </div>
        """, unsafe_allow_html=True)
        
        with st.container(border=True):
            st.subheader("Iniciar Sesión")
            email_login = st.text_input("Correo Electrónico", key="login_email")
            pass_login = st.text_input("Contraseña", type="password", key="login_pass")
            
            st.markdown("")
            if st.button("Ingresar", use_container_width=True, type="primary"):
                if email_login and pass_login:
                    pass_hash = hashlib.sha256(pass_login.encode()).hexdigest()
                    try:
                        with engine.connect() as conn:
                            query = text("SELECT id, nombre_taller, password, fecha_pago_limite FROM Usuarios WHERE email = :email")
                            user = conn.execute(query, {"email": email_login}).fetchone()
                        
                        if user and user[2] == pass_hash:
                            fecha_limite = user[3]
                            hoy = date.today()
                            
                            if fecha_limite is None or fecha_limite < hoy:
                                st.error("⚠️ Tu suscripción se encuentra inactiva o ha expirado. Por favor, comunícate con el administrador para reactivar tu cuenta.")
                            else:
                                st.session_state.user_logged = True
                                st.session_state.user_id = user[0]
                                st.session_state.nombre_taller = user[1]
                                st.rerun()
                        else:
                            st.error("Credenciales incorrectas.")
                    except Exception as e:
                        st.error(f"Error de base de datos. Si dice 'ProgrammingError', usa el botón de arreglo de abajo. Detalle: {e}")
                else:
                    st.warning("Completa todos los campos.")
        
        st.markdown("")
        
        with st.expander("Registrar Nuevo Taller"):
            with st.form("form_registro"):
                taller_reg = st.text_input("Nombre del Taller")
                dueno_reg = st.text_input("Nombre del Dueño")
                email_reg = st.text_input("Correo Electrónico Comercial")
                pass_reg = st.text_input("Contraseña", type="password")
                
                st.markdown("")
                btn_reg = st.form_submit_button("Crear Cuenta", use_container_width=True)
                if btn_reg:
                    if taller_reg and dueno_reg and email_reg and pass_reg:
                        pass_hash_reg = hashlib.sha256(pass_reg.encode()).hexdigest()
                        try:
                            with engine.begin() as conn_reg:
                                conn_reg.execute(
                                    text("""
                                        INSERT INTO Usuarios (nombre_taller, nombre_dueno, email, password)
                                        VALUES (:taller, :dueno, :email, :pass)
                                    """),
                                    {
                                        "taller": taller_reg,
                                        "dueno": dueno_reg,
                                        "email": email_reg,
                                        "pass": pass_hash_reg
                                    }
                                )
                            st.success("Cuenta creada con éxito. Contacta al administrador para activar tu suscripción.")
                        except Exception as e:
                            st.error(f"Error al registrar: {e}")
                    else:
                        st.warning("Completa todos los campos.")
        
        # ==========================================
        # BOTÓN REPARADOR TEMPORAL (AUTO-ACTIVACIÓN)
        # ==========================================
        st.markdown("<hr>", unsafe_allow_html=True)
        if st.button("👑 Activar mi cuenta de Admin", use_container_width=True):
            try:
                with engine.begin() as conn:
                    # Le damos suscripción hasta el año 2036 a tu cuenta administradora
                    conn.execute(
                        text("UPDATE Usuarios SET fecha_pago_limite = '2036-12-31' WHERE email = 'jefferson.david1065@gmail.com'")
                    )
                st.success("✅ ¡Tu cuenta de administrador ha sido activada con éxito! Dale al botón rojo de 'Ingresar' arriba.")
            except Exception as e:
                st.error(f"Error activando cuenta: {e}")

else:
    user_id = st.session_state.user_id
    
    st.title("Panel Principal")
    st.markdown(f"Resumen gerencial y contable para: **{st.session_state.get('nombre_taller', '')}**")
    st.markdown("---")

    with engine.connect() as conn:
        q_valor_activos = text('''
            SELECT SUM(d.precio_venta) 
            FROM Detalles_Orden d
            JOIN Hojas_Trabajo h ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND h.estado != 'Facturado'
        ''')
        total_activos = conn.execute(q_valor_activos, {"uid": user_id}).scalar() or 0.0

        q_cotizar = text('''
            SELECT COUNT(*) FROM Hojas_Trabajo 
            WHERE usuario_id = :uid AND estado = 'Cotizar'
        ''')
        total_cotizar = conn.execute(q_cotizar, {"uid": user_id}).scalar() or 0

        q_ordenes = text('''
            SELECT COUNT(*) FROM Hojas_Trabajo 
            WHERE usuario_id = :uid AND estado != 'Facturado'
        ''')
        total_ordenes_activas = conn.execute(q_ordenes, {"uid": user_id}).scalar() or 0

        q_empresas = text('''
            SELECT COUNT(*) FROM Empresas_Clientes 
            WHERE usuario_id = :uid
        ''')
        total_empresas = conn.execute(q_empresas, {"uid": user_id}).scalar() or 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Valor Trabajos Activos", formato_cop(total_activos))
    m2.metric("Órdenes por Cotizar", total_cotizar)
    m3.metric("Órdenes Activas en Taller", total_ordenes_activas)
    m4.metric("Empresas Registradas", total_empresas)

    st.markdown("---")
    
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        with st.container(border=True):
            st.subheader("Control Contable")
            st.write("Desde este panel puedes supervisar de forma general el estado financiero de tus operaciones en curso. Utiliza los módulos laterales para gestionar la nómina, auditar precios o emitir facturas.")
    with col_info2:
        with st.container(border=True):
            st.subheader("Accesos Rápidos")
            st.write("• Dirígete a Expediente para auditar estados y cotizar pendientes.")
            st.write("• Consulta Nómina Mecánicos para calcular comisiones de personal.")
            st.write("• Gestiona tu cartera de clientes desde el Directorio.")

    st.markdown("")
    if st.button("Cerrar Sesión"):
        st.session_state.user_logged = False
        st.rerun()
