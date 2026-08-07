import streamlit as st
import os
import uuid
import bcrypt
from sqlalchemy import text
from db import obtener_conexion, mensaje_error_amigable
from pdf_utils import IVA_OPCIONES
from queries import (
    obtener_config_taller,
    invalidar_cache_config_taller,
    guardar_datos_taller,
    obtener_operarios_patio,
    invalidar_cache_operarios,
    obtener_credenciales_alegra,
    guardar_credenciales_alegra,
    eliminar_credenciales_alegra,
    tiene_fe_habilitada,
)
import alegra_utils

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
    </style>
""", unsafe_allow_html=True)

# Autenticación
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None, "email": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión para acceder a este módulo.")
    st.stop()

# Bloqueo de rol: los operarios de Patio solo tienen acceso a Recepción.
if st.session_state.auth.get("rol") == "patio":
    st.warning("🔒 Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]

st.title("Configuración del Taller")
st.markdown("Personaliza tu taller, datos de contacto, IVA, logotipo y operarios de patio.")
st.markdown("---")

# Cargar datos actuales del taller (cacheado: antes era una consulta cruda
# sin caché que se repetía en cada rerun de esta página)
datos = obtener_config_taller(user_id)

nombre_actual    = datos[0] if datos else ""
dueno_actual     = datos[1] if datos else ""
email_actual     = datos[2] if datos else ""
logo_path_actual = datos[3] if datos else None
iva_activo_actual      = bool(datos[4]) if datos and datos[4] is not None else False
iva_incluido_actual    = bool(datos[5]) if datos and datos[5] is not None else False
iva_tipo_mo_actual     = datos[6] if datos and datos[6] in IVA_OPCIONES else "Excluido"
iva_tipo_rep_actual    = datos[7] if datos and datos[7] in IVA_OPCIONES else "Excluido"
nit_actual             = datos[8] if datos and datos[8] else ""
telefono_actual        = datos[9] if datos and datos[9] else ""
direccion_actual       = datos[10] if datos and datos[10] else ""
ciudad_actual          = datos[11] if datos and datos[11] else ""

# Carpeta de logos
LOGOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logos")
os.makedirs(LOGOS_DIR, exist_ok=True)

tab_datos, tab_logo, tab_iva, tab_operarios, tab_alegra = st.tabs([
    "Datos del Taller", "Logotipo", "IVA (Colombia)", "Operarios de Patio", "Facturación Electrónica"
])

# ==========================================
# TAB 1: DATOS DEL TALLER
# ==========================================
with tab_datos:
    st.subheader("Información del Taller")
    st.caption("Esta información aparecerá en tus facturas y cotizaciones en PDF.")

    with st.form("form_datos_taller"):
        col1, col2 = st.columns(2)
        with col1:
            nit_input = st.text_input(
                "NIT del Taller", value=nit_actual, placeholder="Ej: 900123456-7",
                help="Número de identificación tributaria de tu taller. Aparece en el encabezado de cada factura."
            )
            telefono_input = st.text_input("Teléfono", value=telefono_actual, placeholder="Ej: 3001234567")
        with col2:
            direccion_input = st.text_input("Dirección", value=direccion_actual, placeholder="Ej: Calle 15 # 10-25")
            ciudad_input    = st.text_input("Ciudad", value=ciudad_actual, placeholder="Ej: Valledupar, Cesar")

        st.markdown("")
        if st.form_submit_button("Guardar Datos", type="primary"):
            try:
                guardar_datos_taller(user_id, nit_input, telefono_input, direccion_input, ciudad_input)
                st.success("Datos guardados. Aparecerán en tus próximas facturas.")
                st.rerun()
            except Exception as e:
                st.error("No se pudieron guardar los datos. Intenta de nuevo en unos segundos.")

    # Mostrar config actual (ya persistida en base de datos)
    if nit_actual or telefono_actual or direccion_actual:
        st.info(f"**Datos guardados:** NIT: {nit_actual or '---'} | Tel: {telefono_actual or '---'} | Dir: {direccion_actual or '---'}")

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
                invalidar_cache_config_taller()

                st.success("¡Logotipo subido exitosamente! Ya aparecerá en tus próximas facturas.")
                st.image(archivo_logo, width=150)

    with col_logo2:
        st.markdown("**Logo actual:**")
        if logo_path_actual and os.path.exists(logo_path_actual):
            st.image(logo_path_actual, width=120)
            if st.button("Eliminar logo"):
                st.session_state.confirmar_eliminar_logo = True

            if st.session_state.get("confirmar_eliminar_logo", False):
                st.warning("¿Quitar el logo? Tus próximas facturas saldrán con el placeholder gris hasta que subas uno nuevo.")
                col_lg1, col_lg2 = st.columns(2)
                with col_lg1:
                    if st.button("Sí, quitar logo", type="primary", use_container_width=True):
                        try:
                            os.remove(logo_path_actual)
                            with engine.begin() as conn:
                                conn.execute(
                                    text("UPDATE Usuarios SET logo_path = NULL WHERE id = :uid"),
                                    {"uid": user_id}
                                )
                            invalidar_cache_config_taller()
                            st.session_state.confirmar_eliminar_logo = False
                            st.success("Logo eliminado.")
                            st.rerun()
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "eliminar el logo"))
                with col_lg2:
                    if st.button("Cancelar", use_container_width=True):
                        st.session_state.confirmar_eliminar_logo = False
                        st.rerun()
        else:
            st.info("Sin logotipo. Se mostrará un placeholder gris en el PDF.")

# ==========================================
# TAB 3: IVA (COLOMBIA)
# ==========================================
with tab_iva:
    st.subheader("Configuración de IVA")
    st.caption(
        "Activa el IVA solo si tu taller está obligado a cobrarlo. Muchos talleres pequeños en Colombia "
        "están en el Régimen Simple de Tributación y no cobran IVA — si ese es tu caso, deja esta opción desactivada."
    )

    with st.form("form_iva"):
        iva_activo_input = st.checkbox(
            "Este taller cobra IVA",
            value=iva_activo_actual,
            help="Si lo desactivas, ningún ítem paga IVA sin importar lo demás (todo se factura como 'Excluido')."
        )

        modo_iva_input = st.radio(
            "¿Cómo manejas el IVA en tus precios?",
            ["El IVA se suma aparte (encima del precio)", "El precio ya incluye el IVA"],
            index=1 if iva_incluido_actual else 0,
            help="Si tus precios ya están calculados con IVA metido, elige la segunda opción."
        )
        iva_incluido_input = (modo_iva_input == "El precio ya incluye el IVA")

        st.markdown("---")
        st.markdown("**Tipo de IVA por defecto para cada categoría**")
        st.caption(
            "Se aplica automáticamente a los ítems que NO tengan un tipo de impuesto elegido "
            "manualmente al agregarlos. En Recepción y Expediente siempre puedes elegir un tipo "
            "distinto para un ítem puntual (ej. una mano de obra exenta puntual), y eso tiene "
            "prioridad sobre este default."
        )
        col_cat1, col_cat2 = st.columns(2)
        with col_cat1:
            iva_tipo_mo_input = st.selectbox(
                "Mano de Obra",
                options=IVA_OPCIONES,
                index=IVA_OPCIONES.index(iva_tipo_mo_actual)
            )
        with col_cat2:
            iva_tipo_rep_input = st.selectbox(
                "Repuestos / Suministros",
                options=IVA_OPCIONES,
                index=IVA_OPCIONES.index(iva_tipo_rep_actual)
            )

        st.markdown("")
        st.caption(
            "💡 Cada producto de Inventario también tiene su propio tipo de IVA editable "
            "(por ejemplo, aceite exento vs. un repuesto con IVA 19%). Ese tipo se hereda "
            "automáticamente cuando tomas el producto del almacén en una orden."
        )

        if st.form_submit_button("Guardar Configuración de IVA", type="primary"):
            try:
                with engine.begin() as conn_iva:
                    conn_iva.execute(
                        text("""
                            UPDATE Usuarios
                            SET iva_activo = :activo, iva_incluido = :incl,
                                iva_tipo_default_mano_obra = :tipo_mo,
                                iva_tipo_default_repuestos = :tipo_rep
                            WHERE id = :uid
                        """),
                        {
                            "activo": iva_activo_input,
                            "incl": iva_incluido_input,
                            "tipo_mo": iva_tipo_mo_input,
                            "tipo_rep": iva_tipo_rep_input,
                            "uid": user_id,
                        }
                    )
                invalidar_cache_config_taller()
                st.success("Configuración de IVA guardada correctamente.")
                st.rerun()
            except Exception as e:
                st.error(mensaje_error_amigable(e, "guardar la configuración de IVA"))

    if iva_activo_actual:
        modo_txt = "incluido en el precio" if iva_incluido_actual else "se suma aparte al precio"
        st.info(f"**Estado actual:** IVA activo, {modo_txt}.")
        col_est1, col_est2 = st.columns(2)
        col_est1.metric("Mano de Obra (default)", iva_tipo_mo_actual)
        col_est2.metric("Repuestos / Suministros (default)", iva_tipo_rep_actual)
    else:
        st.info("**Estado actual:** este taller NO cobra IVA (todos los ítems se facturan como 'Excluido').")

# ==========================================
# TAB 4: OPERARIOS DE PATIO
# ==========================================
with tab_operarios:
    st.subheader("Operarios de Patio")
    st.caption(
        "Crea usuarios de acceso restringido para tu personal de patio. Solo podrán "
        "recepcionar vehículos (placa + cliente), sin ver costos, comisiones ni el resto de módulos."
    )

    with st.expander("➕ Crear nuevo operario", expanded=False):
        with st.form("form_nuevo_operario", clear_on_submit=True):
            nombre_op = st.text_input("Nombre del operario", placeholder="Ej: Carlos Pérez")
            usuario_op = st.text_input(
                "Usuario de acceso",
                placeholder="Ej: carlos.tallerelmotor",
                help="Debe ser único en toda la plataforma. Usa algo fácil de recordar pero difícil de adivinar."
            )
            pass_op = st.text_input("Contraseña", type="password")
            pass_op_confirm = st.text_input("Confirmar contraseña", type="password")

            if st.form_submit_button("Crear Operario", type="primary"):
                if not (nombre_op and usuario_op and pass_op):
                    st.warning("Completa todos los campos.")
                elif pass_op != pass_op_confirm:
                    st.error("Las contraseñas no coinciden.")
                elif len(pass_op) < 4:
                    st.error("La contraseña debe tener al menos 4 caracteres.")
                else:
                    try:
                        pass_hash_op = bcrypt.hashpw(pass_op.encode(), bcrypt.gensalt()).decode()
                        with engine.begin() as conn_op:
                            conn_op.execute(
                                text("""
                                    INSERT INTO Operarios_Patio (usuario_id, nombre_operario, usuario_login, password, activo)
                                    VALUES (:uid, :nom, :login, :pass, TRUE)
                                """),
                                {
                                    "uid": user_id, "nom": nombre_op,
                                    "login": usuario_op.strip(), "pass": pass_hash_op,
                                }
                            )
                        invalidar_cache_operarios()
                        st.success(f"✅ Operario '{nombre_op}' creado con éxito.")
                        st.rerun()
                    except Exception as e:
                        if "UNIQUE" in str(e).upper() or "duplicate" in str(e).lower():
                            st.error("Ese nombre de usuario ya está en uso. Elige otro (ej. agrega un número o el nombre del taller).")
                        else:
                            st.error(mensaje_error_amigable(e, "crear el operario"))

    st.markdown("---")
    st.markdown("#### Operarios registrados")

    operarios = obtener_operarios_patio(user_id)

    if not operarios:
        st.info("Aún no has creado ningún operario de patio.")
    else:
        for op in operarios:
            op_id, op_nombre, op_login, op_activo = op
            with st.container(border=True):
                col_o1, col_o2, col_o3, col_o4 = st.columns([2, 2, 1, 2])
                with col_o1:
                    st.markdown(f"**{op_nombre}**")
                with col_o2:
                    st.caption(f"Usuario: `{op_login}`")
                with col_o3:
                    if op_activo:
                        st.success("Activo")
                    else:
                        st.error("Inactivo")
                with col_o4:
                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        etiqueta_toggle = "Desactivar" if op_activo else "Activar"
                        if st.button(etiqueta_toggle, key=f"toggle_op_{op_id}", use_container_width=True):
                            try:
                                with engine.begin() as conn_toggle:
                                    conn_toggle.execute(
                                        text("UPDATE Operarios_Patio SET activo = :nuevo_estado, token_sesion = NULL WHERE id = :oid AND usuario_id = :uid"),
                                        {"nuevo_estado": not op_activo, "oid": op_id, "uid": user_id}
                                    )
                                invalidar_cache_operarios()
                                st.rerun()
                            except Exception as e:
                                st.error(mensaje_error_amigable(e, "cambiar el estado del operario"))
                    with col_btn2:
                        if st.button("Cambiar clave", key=f"reset_op_{op_id}", use_container_width=True):
                            st.session_state[f"mostrar_reset_{op_id}"] = True

                if st.session_state.get(f"mostrar_reset_{op_id}", False):
                    with st.form(key=f"form_reset_{op_id}"):
                        nueva_pass = st.text_input("Nueva contraseña", type="password", key=f"nueva_pass_{op_id}")
                        col_fr1, col_fr2 = st.columns(2)
                        with col_fr1:
                            if st.form_submit_button("Guardar nueva contraseña", type="primary"):
                                if nueva_pass and len(nueva_pass) >= 4:
                                    try:
                                        nuevo_hash_op = bcrypt.hashpw(nueva_pass.encode(), bcrypt.gensalt()).decode()
                                        with engine.begin() as conn_np:
                                            conn_np.execute(
                                                text("UPDATE Operarios_Patio SET password = :pw, token_sesion = NULL WHERE id = :oid AND usuario_id = :uid"),
                                                {"pw": nuevo_hash_op, "oid": op_id, "uid": user_id}
                                            )
                                        st.session_state[f"mostrar_reset_{op_id}"] = False
                                        st.success("Contraseña actualizada.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(mensaje_error_amigable(e, "actualizar la contraseña"))
                                else:
                                    st.error("La contraseña debe tener al menos 4 caracteres.")
                        with col_fr2:
                            if st.form_submit_button("Cancelar"):
                                st.session_state[f"mostrar_reset_{op_id}"] = False
                                st.rerun()

# ==========================================
# TAB 5: FACTURACIÓN ELECTRÓNICA
# ==========================================
with tab_alegra:
    st.subheader("Facturación Electrónica")

    if not tiene_fe_habilitada(user_id):
        st.info(
            "Esta función todavía no está habilitada para tu taller. "
            "Contacta al administrador para activarla."
        )
        st.stop()

    st.caption(
        "Conecta tu propia cuenta del proveedor de facturación electrónica para poder "
        "emitir facturas desde tus órdenes. Cada taller usa su propia cuenta — la "
        "factura sale a nombre de tu NIT, no del nuestro."
    )

    creds = obtener_credenciales_alegra(user_id)
    conectado = bool(creds and creds.alegra_email and creds.alegra_token)

    if conectado:
        st.success(f"Cuenta conectada: **{creds.alegra_email}**")

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            if st.button("Probar conexión", use_container_width=True):
                with st.spinner("Probando..."):
                    ok, msg = alegra_utils.probar_conexion(creds.alegra_email, creds.alegra_token)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
        with col_a2:
            if st.button("Desconectar cuenta", use_container_width=True):
                st.session_state.confirmar_desconectar_alegra = True

        if st.session_state.get("confirmar_desconectar_alegra", False):
            st.warning("¿Desconectar tu cuenta de Alegra? No podrás emitir facturas electrónicas hasta que conectes una cuenta de nuevo.")
            col_da1, col_da2 = st.columns(2)
            with col_da1:
                if st.button("Sí, desconectar", type="primary", use_container_width=True):
                    eliminar_credenciales_alegra(user_id)
                    st.session_state.confirmar_desconectar_alegra = False
                    st.success("Cuenta desconectada.")
                    st.rerun()
            with col_da2:
                if st.button("Cancelar", use_container_width=True):
                    st.session_state.confirmar_desconectar_alegra = False
                    st.rerun()

        st.markdown("---")
        st.markdown("**Cambiar de cuenta:**")

    with st.form("form_alegra"):
        st.caption(
            "Consigue estos datos en tu cuenta de Alegra: "
            "Configuración → \"API - Integraciones con otros sistemas\"."
        )
        email_alegra_input = st.text_input("Email de tu cuenta Alegra", placeholder="tucorreo@ejemplo.com")
        token_alegra_input = st.text_input("Token de Alegra", type="password")

        if st.form_submit_button("Guardar y probar conexión", type="primary"):
            if not email_alegra_input or not token_alegra_input:
                st.warning("Completa ambos campos.")
            else:
                with st.spinner("Validando credenciales..."):
                    ok, msg = alegra_utils.probar_conexion(email_alegra_input, token_alegra_input)
                if ok:
                    guardar_credenciales_alegra(user_id, email_alegra_input, token_alegra_input)
                    st.success("Credenciales válidas y guardadas. Ya puedes facturar electrónicamente.")
                    st.rerun()
                else:
                    st.error(f"No se guardó: {msg}")

st.markdown("---")
st.caption("💡 **Tip:** Después de subir tu logo, descarga una factura de prueba en Expediente para verificar cómo queda.")
