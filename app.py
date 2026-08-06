import streamlit as st
import pandas as pd
import bcrypt
import hashlib
import uuid
from sqlalchemy import text
from db import obtener_conexion, init_db, mensaje_error_amigable
from queries import obtener_metricas_dashboard, obtener_metricas_financieras, buscar_ordenes, obtener_creditos_pendientes
from datetime import datetime, date

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MyTaller",
    layout="wide",
    initial_sidebar_state="expanded" if st.session_state.get("auth", {}).get("logged", False) else "collapsed"
)

# Inicializar Base de Datos (cacheada como recurso en db.py -> se ejecuta 1 sola vez)
init_db()

# --------------------------------------------------------------------------------
# 2. SESSION STATE NAMESPACED CON PERSISTENCIA
# --------------------------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {
        "logged": False,
        "user_id": None,
        "nombre_taller": None,
        "email": None,
        "token": None,
        "rol": None,              # "admin" o "patio"
        "operario_id": None,      # solo si rol == "patio"
        "operario_nombre": None,  # solo si rol == "patio"
    }

is_logged = st.session_state.auth["logged"]

# --------------------------------------------------------------------------------
# Verificar si hay token en la URL (query params) al cargar la página.
# Primero se busca entre los dueños de taller (Usuarios); si no hay coincidencia,
# se busca entre los Operarios de Patio.
# --------------------------------------------------------------------------------
if not st.session_state.auth["logged"]:
    token_en_url = st.query_params.get("token")
    if token_en_url:
        engine_verify = obtener_conexion()
        try:
            with engine_verify.connect() as conn_verify:
                usuario_token = conn_verify.execute(
                    text("SELECT id, nombre_taller, email FROM Usuarios WHERE token_sesion = :token"),
                    {"token": token_en_url}
                ).fetchone()

            if usuario_token:
                # Token válido de dueño de taller, auto-login como admin
                st.session_state.auth["logged"] = True
                st.session_state.auth["user_id"] = usuario_token[0]
                st.session_state.auth["nombre_taller"] = usuario_token[1]
                st.session_state.auth["email"] = usuario_token[2]
                st.session_state.auth["token"] = token_en_url
                st.session_state.auth["rol"] = "admin"
                st.rerun()
            else:
                # No es un dueño de taller: buscar entre Operarios de Patio
                with engine_verify.connect() as conn_verify2:
                    operario_token = conn_verify2.execute(
                        text('''
                            SELECT o.id, o.nombre_operario, o.usuario_id, u.nombre_taller
                            FROM Operarios_Patio o
                            JOIN Usuarios u ON o.usuario_id = u.id
                            WHERE o.token_sesion = :token AND o.activo = TRUE
                        '''),
                        {"token": token_en_url}
                    ).fetchone()

                if operario_token:
                    st.session_state.auth["logged"] = True
                    st.session_state.auth["user_id"] = operario_token[2]
                    st.session_state.auth["nombre_taller"] = operario_token[3]
                    st.session_state.auth["email"] = None
                    st.session_state.auth["token"] = token_en_url
                    st.session_state.auth["rol"] = "patio"
                    st.session_state.auth["operario_id"] = operario_token[0]
                    st.session_state.auth["operario_nombre"] = operario_token[1]
                    st.rerun()
        except Exception:
            # Si hay error, simplemente continúa con login normal
            pass

# Actualizar is_logged después de verificar token
is_logged = st.session_state.auth["logged"]

# --------------------------------------------------------------------------------
# 3. ESTILOS CSS ADAPTABLES AL TEMA (CLARO/OSCURO)
# --------------------------------------------------------------------------------
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

    """ + ("" if is_logged else """
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    """) + """

    [data-testid="stSidebarNav"] ul li:last-child {
        margin-top: 50px !important;
        border-top: 1px solid rgba(255, 255, 255, 0.12) !important;
        padding-top: 10px !important;
    }

    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out; }
    </style>
""", unsafe_allow_html=True)

engine = obtener_conexion()


def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")


# --------------------------------------------------------------------------------
# 5. PANTALLAS
# --------------------------------------------------------------------------------
if not is_logged:
    # ---------------- Inicio de Sesión ----------------
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
                    try:
                        with engine.connect() as conn:
                            query = text(
                                "SELECT id, nombre_taller, password, fecha_pago_limite "
                                "FROM Usuarios WHERE email = :email"
                            )
                            user = conn.execute(query, {"email": email_login}).fetchone()

                        credenciales_ok = False
                        if user is not None:
                            hash_guardado = user[2]

                            if hash_guardado.startswith(("$2a$", "$2b$", "$2y$")):
                                # Ya migrado: hash bcrypt normal
                                credenciales_ok = bcrypt.checkpw(
                                    pass_login.encode(), hash_guardado.encode()
                                )
                            else:
                                # Hash legado en SHA-256: se verifica como antes
                                # y, si coincide, se migra a bcrypt en silencio.
                                hash_sha256 = hashlib.sha256(pass_login.encode()).hexdigest()
                                if hash_sha256 == hash_guardado:
                                    credenciales_ok = True
                                    nuevo_hash = bcrypt.hashpw(
                                        pass_login.encode(), bcrypt.gensalt()
                                    ).decode()
                                    with engine.begin() as conn_migra:
                                        conn_migra.execute(
                                            text("UPDATE Usuarios SET password = :pw WHERE id = :uid"),
                                            {"pw": nuevo_hash, "uid": user[0]},
                                        )

                        if credenciales_ok:
                            fecha_limite = user[3]
                            if isinstance(fecha_limite, str):
                                fecha_limite = datetime.strptime(fecha_limite, "%Y-%m-%d").date()
                            hoy = date.today()

                            if fecha_limite is None or fecha_limite < hoy:
                                st.error(
                                    "Tu suscripción se encuentra inactiva o ha expirado. "
                                    "Por favor, comunícate con el administrador para reactivar tu cuenta."
                                )
                            else:
                                # Generar token de sesión para persistencia
                                token_nuevo = str(uuid.uuid4())

                                # Guardar token en la BD
                                with engine.begin() as conn_token:
                                    conn_token.execute(
                                        text("UPDATE Usuarios SET token_sesion = :token WHERE id = :uid"),
                                        {"token": token_nuevo, "uid": user[0]}
                                    )

                                # Guardar en session_state
                                st.session_state.auth = {
                                    "logged": True,
                                    "user_id": user[0],
                                    "nombre_taller": user[1],
                                    "email": email_login,
                                    "token": token_nuevo,
                                    "rol": "admin",
                                    "operario_id": None,
                                    "operario_nombre": None,
                                }

                                # Pasar token en URL para que persista entre recargas
                                st.query_params["token"] = token_nuevo

                                st.success(f"¡Bienvenido, {user[1]}!")
                                st.rerun()
                        else:
                            st.error("Credenciales incorrectas.")
                    except Exception as e:
                        st.error(mensaje_error_amigable(e, "iniciar sesión"))
                else:
                    st.warning("Completa todos los campos.")

        st.markdown("")

        # ---------------- Acceso de Patio (Operarios) ----------------
        with st.expander("🔧 Acceso de Patio (Recepción de Vehículos)"):
            st.caption("Acceso exclusivo para operarios de patio. Solo permite recepcionar vehículos.")
            usuario_patio = st.text_input("Usuario", key="login_patio_user")
            pass_patio = st.text_input("Contraseña", type="password", key="login_patio_pass")

            if st.button("Ingresar como Patio", use_container_width=True, key="btn_login_patio"):
                if usuario_patio and pass_patio:
                    try:
                        with engine.connect() as conn_p:
                            operario = conn_p.execute(
                                text('''
                                    SELECT o.id, o.nombre_operario, o.password, o.usuario_id,
                                           u.nombre_taller, o.activo
                                    FROM Operarios_Patio o
                                    JOIN Usuarios u ON o.usuario_id = u.id
                                    WHERE o.usuario_login = :login
                                '''),
                                {"login": usuario_patio.strip()}
                            ).fetchone()

                        cred_patio_ok = False
                        if operario and operario[5]:
                            hash_guardado_p = operario[2]
                            if hash_guardado_p.startswith(("$2a$", "$2b$", "$2y$")):
                                cred_patio_ok = bcrypt.checkpw(pass_patio.encode(), hash_guardado_p.encode())

                        if cred_patio_ok:
                            token_patio = str(uuid.uuid4())
                            with engine.begin() as conn_tp:
                                conn_tp.execute(
                                    text("UPDATE Operarios_Patio SET token_sesion = :token WHERE id = :oid"),
                                    {"token": token_patio, "oid": operario[0]}
                                )

                            st.session_state.auth = {
                                "logged": True,
                                "user_id": operario[3],
                                "nombre_taller": operario[4],
                                "email": None,
                                "token": token_patio,
                                "rol": "patio",
                                "operario_id": operario[0],
                                "operario_nombre": operario[1],
                            }
                            st.query_params["token"] = token_patio
                            st.rerun()
                        elif operario and not operario[5]:
                            st.error("Este usuario de patio está desactivado. Contacta al administrador del taller.")
                        else:
                            st.error("Usuario o contraseña incorrectos.")
                    except Exception as e:
                        st.error(mensaje_error_amigable(e, "iniciar sesión"))
                else:
                    st.warning("Completa usuario y contraseña.")

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
                        pass_hash_reg = bcrypt.hashpw(
                            pass_reg.encode(), bcrypt.gensalt()
                        ).decode()
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
                                        "pass": pass_hash_reg,
                                    },
                                )
                            # No se limpia cache global: el registro no afecta
                            # métricas cacheadas de otros usuarios.
                            st.success(
                                "Cuenta creada con éxito. Contacta al administrador "
                                "para activar tu suscripción."
                            )
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "registrar el taller"))
                    else:
                        st.warning("Completa todos los campos.")

elif st.session_state.auth.get("rol") == "patio":
    # ---------------- Panel simplificado para Operario de Patio ----------------
    st.markdown(f"""
        <div style='text-align: center; margin-top: 40px; margin-bottom: 10px;'>
            <h1 style='font-weight: 800; font-size: 2rem; letter-spacing: -1px;'>
                My<span style='color: #FF4B4B;'>Taller</span> — Patio
            </h1>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.container(border=True):
            st.subheader(f"👋 Hola, {st.session_state.auth['operario_nombre']}")
            st.write(f"**Taller:** {st.session_state.auth['nombre_taller']}")
            st.write("Tu usuario solo tiene acceso al módulo de **Recepción de Vehículos**.")
            st.markdown("")
            if st.button("➡️ Ir a Recepción de Vehículos", type="primary", use_container_width=True):
                try:
                    st.switch_page("pages/1_Recepción.py")
                except Exception:
                    st.info("Abre el módulo **'Recepción'** desde el menú lateral.")

        st.markdown("")
        if st.button("Cerrar Sesión", use_container_width=True):
            try:
                with engine.begin() as conn_out:
                    conn_out.execute(
                        text("UPDATE Operarios_Patio SET token_sesion = NULL WHERE id = :oid"),
                        {"oid": st.session_state.auth["operario_id"]}
                    )
            except Exception:
                pass
            st.session_state.auth = {
                "logged": False, "user_id": None, "nombre_taller": None, "email": None,
                "token": None, "rol": None, "operario_id": None, "operario_nombre": None,
            }
            if "token" in st.query_params:
                del st.query_params["token"]
            st.rerun()

else:
    # ---------------- Panel Principal (Admin) ----------------
    user_id = st.session_state.auth["user_id"]

    st.title("Panel Principal")
    st.markdown(f"Resumen gerencial y contable para: **{st.session_state.auth['nombre_taller']}**")
    st.markdown("---")

    # ---------------- Buscador rápido de órdenes/placas ----------------
    with st.form("form_busqueda_global", clear_on_submit=False):
        col_bg1, col_bg2 = st.columns([5, 1])
        with col_bg1:
            termino_busqueda_global = st.text_input(
                "Buscar orden",
                placeholder="Busca por N° de orden o placa (ej: 123 o ABC123)",
                label_visibility="collapsed",
            )
        with col_bg2:
            buscar_global_click = st.form_submit_button("🔍 Buscar", use_container_width=True)

    # Los resultados se guardan en session_state (no solo en una variable local)
    # porque al hacer clic en "Ir a esta orden" Streamlit vuelve a correr todo
    # el script desde cero: si los resultados solo vivieran en la rama del
    # "if buscar_global_click", desaparecerían justo antes de poder navegar.
    if buscar_global_click and termino_busqueda_global.strip():
        st.session_state["resultados_busqueda_global"] = buscar_ordenes(user_id, termino_busqueda_global)
        st.session_state["termino_busqueda_global_mostrado"] = termino_busqueda_global

    resultados_busqueda_global = st.session_state.get("resultados_busqueda_global")
    if resultados_busqueda_global is not None:
        termino_mostrado = st.session_state.get("termino_busqueda_global_mostrado", "")
        if not resultados_busqueda_global:
            st.warning(f"No se encontró ninguna orden que coincida con '{termino_mostrado}'.")
        elif len(resultados_busqueda_global) == 1:
            st.session_state["orden_busqueda_valor"] = str(resultados_busqueda_global[0][0])
            del st.session_state["resultados_busqueda_global"]
            st.switch_page("pages/3_Facturación_e_historial.py")
        else:
            st.info(f"Se encontraron {len(resultados_busqueda_global)} órdenes. Elige una para abrirla:")
            for r in resultados_busqueda_global:
                oid_r, placa_r, cliente_r, fecha_r, estado_r = r
                if st.button(
                    f"Orden #{oid_r} — Placa {placa_r} — {cliente_r} — {fecha_r} — {estado_r}",
                    key=f"ir_orden_global_{oid_r}", use_container_width=True
                ):
                    st.session_state["orden_busqueda_valor"] = str(oid_r)
                    del st.session_state["resultados_busqueda_global"]
                    st.switch_page("pages/3_Facturación_e_historial.py")

    st.markdown("---")

    total_activos, total_cotizar, total_ordenes_activas, total_empresas = obtener_metricas_dashboard(user_id)

    # Calcular margen neto del mes actual (cacheado, ttl=60s: antes eran dos
    # consultas crudas sin caché que se repetían en cada rerun del dashboard)
    hoy = datetime.today()
    ingresos_mes, gastos_mes = obtener_metricas_financieras(user_id, hoy.year, hoy.month)
    margen_neto = ingresos_mes - gastos_mes

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Valor Trabajos Activos", formato_cop(total_activos))
    m2.metric("Órdenes por Cotizar", total_cotizar)
    m3.metric("Órdenes Activas en Taller", total_ordenes_activas)
    m4.metric("Empresas Registradas", total_empresas)

    st.markdown("---")

    col_mes1, col_mes2, col_mes3 = st.columns(3)
    col_mes1.metric("Ingresos Mes Actual", formato_cop(ingresos_mes))
    col_mes2.metric("Gastos Mes Actual", formato_cop(gastos_mes), delta=f"-{formato_cop(gastos_mes)}")
    col_mes3.metric("Margen Neto Mes", formato_cop(margen_neto), delta_color="inverse" if margen_neto < 0 else "normal")

    # ---------------- Aviso de créditos vencidos ----------------
    # Antes esto solo se veía si el dueño entraba a Cartera por su cuenta;
    # ahora aparece de una vez en el panel principal, difícil de pasar por alto.
    df_creditos_dash = obtener_creditos_pendientes(user_id)
    if not df_creditos_dash.empty:
        vencidos_dash = df_creditos_dash[df_creditos_dash['vencido'] == True]
        if not vencidos_dash.empty:
            total_vencido_dash = vencidos_dash['saldo_pendiente'].sum()
            st.markdown("---")
            st.error(
                f"⚠️ Tienes **{len(vencidos_dash)} crédito(s) vencido(s)** por "
                f"{formato_cop(total_vencido_dash)}. Revisa el detalle en el módulo **Cartera**."
            )

    st.markdown("---")

    col_info1, col_info2 = st.columns(2)
    with col_info1:
        with st.container(border=True):
            st.subheader("Control Contable")
            st.write(
                "Desde este panel puedes supervisar de forma general el estado "
                "financiero de tus operaciones en curso. Utiliza los módulos "
                "laterales para gestionar la nómina, auditar precios o emitir facturas."
            )
    with col_info2:
        with st.container(border=True):
            st.subheader("Accesos Rápidos")
            st.write("• Dirígete a Facturación e historial para auditar estados y cotizar pendientes.")
            st.write("• Consulta Nómina Mecánicos para calcular comisiones de personal.")
            st.write("• Gestiona tus clientes desde Registros, y revisa los créditos pendientes por cobrar en Cartera.")

    st.markdown("")
    if st.button("Cerrar Sesión"):
        # Limpiar token en la BD
        try:
            with engine.begin() as conn_logout:
                conn_logout.execute(
                    text("UPDATE Usuarios SET token_sesion = NULL WHERE id = :uid"),
                    {"uid": st.session_state.auth["user_id"]}
                )
        except Exception as e:
            st.warning(f"Error al limpiar sesión: {e}")

        # Limpiar session_state
        st.session_state.auth = {
            "logged": False, "user_id": None, "nombre_taller": None, "email": None,
            "token": None, "rol": None, "operario_id": None, "operario_nombre": None,
        }

        # Limpiar token de la URL
        if "token" in st.query_params:
            del st.query_params["token"]

        st.rerun()
