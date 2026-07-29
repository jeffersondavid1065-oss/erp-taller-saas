import streamlit as st
import os
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Configuración del Taller", layout="wide")

st.markdown("""
    <style>
    header::after {
        content: "";
        position: fixed !important;
        top: 0 !important;
        right: 0 !important;
        width: 350px !important;
        height: 60px !important;
        background-color: var(--background-color) !important;
        z-index: 9999999 !important;
        pointer-events: all !important;
    }
    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out; }
    </style>
""", unsafe_allow_html=True)

# Autenticación
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None, "email": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]

st.title("Configuración del Taller")
st.markdown("Personaliza tu taller, datos de contacto y logotipo para documentos y facturas.")
st.markdown("---")

# Cargar datos actuales del taller
with engine.connect() as conn:
    datos = conn.execute(
        text("SELECT nombre_taller, nombre_dueno, email, logo_path FROM Usuarios WHERE id = :uid"),
        {"uid": user_id}
    ).fetchone()

nombre_actual    = datos[0] if datos else ""
dueno_actual     = datos[1] if datos else ""
email_actual     = datos[2] if datos else ""
logo_path_actual = datos[3] if datos else None

# Carpeta de logos
LOGOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logos")
os.makedirs(LOGOS_DIR, exist_ok=True)

tab_datos, tab_logo = st.tabs(["Datos del Taller", "Logotipo"])

# ==========================================
# TAB 1: DATOS DEL TALLER
# ==========================================
with tab_datos:
    st.subheader("Información del Taller")
    st.caption("Esta información aparecerá en tus facturas y cotizaciones en PDF.")

    with st.form("form_datos_taller"):
        col1, col2 = st.columns(2)
        with col1:
            nit_input       = st.text_input("NIT del Taller", placeholder="Ej: 900123456-7")
            telefono_input  = st.text_input("Teléfono", placeholder="Ej: 3001234567")
        with col2:
            direccion_input = st.text_input("Dirección", placeholder="Ej: Calle 15 # 10-25, Valledupar")
            ciudad_input    = st.text_input("Ciudad", placeholder="Ej: Valledupar, Cesar")

        st.markdown("")
        if st.form_submit_button("Guardar Datos", type="primary"):
            try:
                # Guardar en session_state para uso inmediato
                st.session_state.taller_config = {
                    "nit": nit_input,
                    "telefono": telefono_input,
                    "direccion": f"{direccion_input}, {ciudad_input}".strip(", "),
                    "ciudad": ciudad_input,
                }
                st.success("Datos guardados. Aparecerán en tus próximas facturas.")
            except Exception as e:
                st.error(f"Error al guardar: {e}")

    # Mostrar config actual
    if "taller_config" in st.session_state:
        cfg = st.session_state.taller_config
        st.info(f"**Config actual:** NIT: {cfg.get('nit','---')} | Tel: {cfg.get('telefono','---')} | Dir: {cfg.get('direccion','---')}")

# ==========================================
# TAB 2: LOGOTIPO
# ==========================================
with tab_logo:
    st.subheader("Logotipo del Taller")
    st.caption("Sube tu logo para que aparezca en las facturas y cotizaciones en PDF. Formatos: PNG o JPG. Máximo 2MB.")

    col_logo1, col_logo2 = st.columns([2, 1])

    with col_logo1:
        archivo_logo = st.file_uploader(
            "Subir logotipo",
            type=["png", "jpg", "jpeg"],
            help="Recomendado: imagen cuadrada, mínimo 200x200px, fondo blanco o transparente (PNG)."
        )

        if archivo_logo is not None:
            # Verificar tamaño (máximo 2MB)
            if archivo_logo.size > 2 * 1024 * 1024:
                st.error("El archivo es demasiado grande. Máximo 2MB.")
            else:
                # Guardar el archivo en el servidor
                ext = archivo_logo.name.split(".")[-1].lower()
                logo_filename = f"logo_{user_id}.{ext}"
                logo_path = os.path.join(LOGOS_DIR, logo_filename)

                with open(logo_path, "wb") as f:
                    f.write(archivo_logo.getbuffer())

                # Guardar la ruta en la BD
                with engine.begin() as conn:
                    conn.execute(
                        text("UPDATE Usuarios SET logo_path = :logo WHERE id = :uid"),
                        {"logo": logo_path, "uid": user_id}
                    )

                # Actualizar session_state
                if "taller_config" not in st.session_state:
                    st.session_state.taller_config = {}
                st.session_state.taller_config["logo_path"] = logo_path

                st.success("¡Logotipo subido exitosamente! Ya aparecerá en tus próximas facturas.")
                st.image(archivo_logo, width=150)

    with col_logo2:
        st.markdown("**Logo actual:**")
        if logo_path_actual and os.path.exists(logo_path_actual):
            st.image(logo_path_actual, width=120)
            if st.button("Eliminar logo"):
                try:
                    os.remove(logo_path_actual)
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE Usuarios SET logo_path = NULL WHERE id = :uid"),
                            {"uid": user_id}
                        )
                    st.success("Logo eliminado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al eliminar: {e}")
        else:
            st.info("Sin logotipo. Se mostrará un placeholder gris en el PDF.")

st.markdown("---")
st.caption("💡 **Tip:** Después de subir tu logo, descarga una factura de prueba en Expediente para verificar cómo queda.")
