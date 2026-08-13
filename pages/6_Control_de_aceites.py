import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion, mensaje_error_amigable
from queries import obtener_catalogos, obtener_mecanicos_activos, invalidar_cache_inventario, obtener_metricas_financieras, obtener_siguiente_numero_orden

# Animaciones y estilos
st.markdown("""
    <style>
    header::after {
        content: ""; position: fixed !important; top: 0 !important; right: 0 !important;
        width: 350px !important; height: 60px !important;
        background-color: var(--background-color) !important;
        z-index: 9999999 !important; pointer-events: all !important;
    }

    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out !important; }
    div[data-testid="stVerticalBlock"] > div { animation: fade-in-up 0.5s ease-out !important; }
    </style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------------
# AUTENTICACIÓN: mismo namespace st.session_state.auth definido en app.py
# --------------------------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

# Bloqueo de rol: los operarios de Patio solo tienen acceso a Recepción.
if st.session_state.auth.get("rol") == "patio":
    st.warning("Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

# ==========================================
# CONSULTAS CACHEADAS ESPECÍFICAS DE ESTE MÓDULO
# ==========================================
@st.cache_data(ttl=60)
def obtener_agenda_flota(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("""
                SELECT v.id, v.placa, v.modelo_vehiculo, e.razon_social as empresa, 
                       v.fecha_ultimo_servicio, v.fecha_proximo_servicio, v.kilometraje_actual
                FROM Vehiculos_Flota v
                JOIN Empresas_Clientes e ON v.empresa_id = e.id
                WHERE v.usuario_id = :uid
                ORDER BY v.fecha_proximo_servicio ASC
            """),
            con=conn, params={"uid": uid}
        )

@st.cache_data(ttl=60)
def obtener_vehiculos_flota(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("SELECT v.id, v.placa, v.modelo_vehiculo, e.razon_social FROM Vehiculos_Flota v "
                 "JOIN Empresas_Clientes e ON v.empresa_id = e.id WHERE v.usuario_id = :uid ORDER BY v.placa ASC"),
            con=conn, params={"uid": uid}
        )

@st.cache_data(ttl=30)
def obtener_vehiculo_por_id(vid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM Vehiculos_Flota WHERE id = :vid"), {"vid": vid}).fetchone()

@st.cache_data(ttl=30)
def obtener_receta_vehiculo(vid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text("""
                SELECT r.id, i.nombre_producto, r.cantidad, i.precio_venta, i.id as inv_id
                FROM Recetas_Vehiculo r
                JOIN Inventario i ON r.inventario_id = i.id
                WHERE r.vehiculo_id = :vid
            """),
            con=conn, params={"vid": vid}
        )

def invalidar_cache_flota():
    """Llamar tras crear un vehículo o actualizar sus datos (fechas, km)."""
    obtener_agenda_flota.clear()
    obtener_vehiculos_flota.clear()
    obtener_vehiculo_por_id.clear()

def invalidar_cache_receta():
    """Llamar tras agregar/eliminar un insumo de la receta de un vehículo."""
    obtener_receta_vehiculo.clear()

st.title("Control de Cambios de Aceite y Flotas")
st.markdown(f"Mantenimiento preventivo e insumos para: **{nombre_taller}**")
st.markdown("---")

tab_agenda, tab_flota = st.tabs(["Agenda y Proximos Servicios", "Gestion de Vehiculos y Filtros"])

# ==========================================
# PESTAÑA 1: AGENDA Y RECORDATORIOS
# ==========================================
with tab_agenda:
    st.subheader("Vehiculos con Mantenimiento Proximo o Vencido")

    df_agenda = obtener_agenda_flota(user_id)

    if not df_agenda.empty:
        hoy = datetime.today().date()
        df_agenda['fecha_proximo_servicio'] = pd.to_datetime(df_agenda['fecha_proximo_servicio']).dt.date
        
        for idx, row in df_agenda.iterrows():
            dias_restantes = (row['fecha_proximo_servicio'] - hoy).days if pd.notnull(row['fecha_proximo_servicio']) else 0
            
            with st.container(border=True):
                col_a1, col_a2, col_a3, col_a4 = st.columns([2, 2, 2, 2])
                with col_a1:
                    st.markdown(f"#### Placa: {row['placa']}")
                    st.caption(f"Cliente: {row['empresa']}")
                with col_a2:
                    st.write(f"**Vehiculo:** {row['modelo_vehiculo'] or 'No especificado'}")
                    st.write(f"**Km Actual:** {row['kilometraje_actual']:,}")
                with col_a3:
                    st.write(f"**Ultimo Serv:** {row['fecha_ultimo_servicio'] or 'N/A'}")
                    st.write(f"**Proximo Serv:** {row['fecha_proximo_servicio']}")
                with col_a4:
                    if dias_restantes < 0:
                        st.error(f"Vencido hace {abs(dias_restantes)} dias")
                    elif dias_restantes <= 10:
                        st.warning(f"Programado en {dias_restantes} dias")
                    else:
                        st.success(f"Al dia (en {dias_restantes} dias)")
    else:
        st.info("No hay vehiculos registrados en el sistema de flotas todavia.")

# ==========================================
# PESTAÑA 2: GESTION DE VEHICULOS Y FILTROS
# ==========================================
with tab_flota:
    with st.expander("Registrar Nuevo Vehiculo a una Empresa", expanded=False):
        empresas, _ = obtener_catalogos(user_id)

        if empresas:
            dict_emp = {e[1]: e[0] for e in empresas}
            with st.form("form_nuevo_vehiculo", clear_on_submit=True):
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    placa_v = st.text_input("Placa del Vehiculo").upper().strip()
                    empresa_sel_v = st.selectbox("Empresa / Propietario", options=list(dict_emp.keys()))
                    modelo_v = st.text_input("Modelo / Marca (Ej: Chevrolet NPR)")
                with col_f2:
                    km_v = st.number_input("Kilometraje Actual", min_value=0, value=50000, step=1000)
                    intervalo_v = st.number_input("Intervalo de Recordatorio (Meses)", min_value=1, value=3, step=1)
                    fecha_ult_v = st.date_input("Fecha del Ultimo Servicio", value=datetime.today())

                if st.form_submit_button("Guardar Vehiculo", type="primary"):
                    if placa_v:
                        try:
                            proxima_fecha = fecha_ult_v + timedelta(days=int(intervalo_v * 30))
                            with engine.begin() as conn_v:
                                conn_v.execute(
                                    text("""
                                        INSERT INTO Vehiculos_Flota (usuario_id, empresa_id, placa, modelo_vehiculo, fecha_ultimo_servicio, fecha_proximo_servicio, kilometraje_actual, intervalo_meses)
                                        VALUES (:uid, :eid, :placa, :modelo, :f_ult, :f_prox, :km, :inter)
                                    """),
                                    {"uid": user_id, "eid": dict_emp[empresa_sel_v], "placa": placa_v, "modelo": modelo_v, "f_ult": fecha_ult_v.strftime('%Y-%m-%d'), "f_prox": proxima_fecha.strftime('%Y-%m-%d'), "km": int(km_v), "inter": int(intervalo_v)}
                                )
                            invalidar_cache_flota()
                            st.success(f"Vehiculo {placa_v} registrado.")
                            st.rerun()
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "registrar el vehículo"))
                    else:
                        st.warning("La placa es obligatoria.")
        else:
            st.info("Primero debes registrar empresas en el Directorio.")

    st.markdown("---")

    vehiculos_db = obtener_vehiculos_flota(user_id)

    if not vehiculos_db.empty:
        dict_veh = {f"{r['placa']} - {r['modelo_vehiculo']} ({r['razon_social']})": r['id'] for idx, r in vehiculos_db.iterrows()}
        veh_sel_str = st.selectbox("Selecciona un vehiculo para configurar o despachar:", options=list(dict_veh.keys()))
        veh_id_activo = int(dict_veh[veh_sel_str])

        veh_info = obtener_vehiculo_por_id(veh_id_activo)

        st.info(f"Placa: {veh_info[3]} | Ultimo servicio: {veh_info[5] or 'Pendiente'} | Proximo: {veh_info[6]}")

        tab_receta, tab_despacho = st.tabs(["Configurar Filtros e Insumos (Lista)", "Generar Orden de Trabajo (Despachar)"])

        # ==========================================
        # PESTAÑA: CONFIGURAR RECETA E INVENTARIO
        # ==========================================
        with tab_receta:
            st.write("Agrega los insumos uno por uno. Ejemplo: agrega 1 Filtro de Aceite, luego 2 Filtros de ACPM, luego 4 Cuartos de Aceite.")

            recetas_df = obtener_receta_vehiculo(veh_id_activo)

            if not recetas_df.empty:
                st.markdown("**Insumos actuales del vehiculo:**")
                for idx, row in recetas_df.iterrows():
                    col_item1, col_item2, col_item3, col_item4 = st.columns([3, 1, 2, 1])
                    col_item1.write(f"{row['nombre_producto']}")
                    col_item2.write(f"Cant: {row['cantidad']}")
                    col_item3.write(f"Unidad: {formato_cop(row['precio_venta'])}")
                    with col_item4:
                        if st.button("Eliminar", key=f"del_receta_{row['id']}"):
                            st.session_state[f"del_confirm_receta_{row['id']}"] = True

                    if st.session_state.get(f"del_confirm_receta_{row['id']}", False):
                        col_rc1, col_rc2, col_rc3 = st.columns([2, 1, 1])
                        col_rc1.warning(f"¿Quitar **{row['nombre_producto']}** de la lista de este vehículo?")
                        with col_rc2:
                            if st.button("Sí, quitar", key=f"yes_del_receta_{row['id']}", type="primary", width='stretch'):
                                try:
                                    with engine.begin() as conn_del:
                                        conn_del.execute(text("DELETE FROM Recetas_Vehiculo WHERE id = :rid"), {"rid": row['id']})
                                    invalidar_cache_receta()
                                    st.session_state[f"del_confirm_receta_{row['id']}"] = False
                                    st.success("Insumo eliminado de la lista.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(mensaje_error_amigable(e, "eliminar el insumo"))
                        with col_rc3:
                            if st.button("Cancelar", key=f"no_del_receta_{row['id']}", width='stretch'):
                                st.session_state[f"del_confirm_receta_{row['id']}"] = False
                                st.rerun()
            else:
                st.caption("No hay insumos configurados para este vehiculo.")

            st.markdown("---")
            with st.form("form_add_receta_inventario", clear_on_submit=True):
                st.markdown("**Agregar Insumo a la Lista**")
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    item_desc = st.text_input("Nombre del Filtro o Aceite (Ej: Filtro ACPM, Cuarto Aceite 15W40)")
                    cant_item = st.number_input("Cantidad que usa el carro", min_value=1, value=1, step=1)
                with col_r2:
                    costo_compra = st.number_input("Costo de Compra ($)", min_value=0.0, step=1000.0)
                    precio_venta = st.number_input("Precio de Venta ($)", min_value=0.0, step=1000.0)

                if st.form_submit_button("Guardar en Lista y Almacen", type="primary"):
                    if item_desc:
                        try:
                            with engine.begin() as conn_r:
                                is_sqlite = "sqlite" in str(conn_r.engine.url)
                                if is_sqlite:
                                    cur = conn_r.execute(
                                        text("INSERT INTO Inventario (usuario_id, nombre_producto, costo_compra, precio_venta, stock_actual) VALUES (:uid, :nom, :costo, :pvp, 0)"),
                                        {"uid": user_id, "nom": item_desc, "costo": float(costo_compra), "pvp": float(precio_venta)}
                                    )
                                    nuevo_inv_id = cur.lastrowid
                                else:
                                    res = conn_r.execute(
                                        text("INSERT INTO Inventario (usuario_id, nombre_producto, costo_compra, precio_venta, stock_actual) VALUES (:uid, :nom, :costo, :pvp, 0) RETURNING id"),
                                        {"uid": user_id, "nom": item_desc, "costo": float(costo_compra), "pvp": float(precio_venta)}
                                    )
                                    nuevo_inv_id = res.scalar()

                                conn_r.execute(
                                    text("INSERT INTO Recetas_Vehiculo (vehiculo_id, inventario_id, cantidad) VALUES (:vid, :iid, :cant)"),
                                    {"vid": veh_id_activo, "iid": nuevo_inv_id, "cant": int(cant_item)}
                                )
                            invalidar_cache_receta()
                            invalidar_cache_inventario()
                            st.success("Insumo guardado.")
                            st.rerun()
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "guardar el insumo"))

        # ==========================================
        # PESTAÑA: DESPACHO Y ORDENES
        # ==========================================
        with tab_despacho:
            st.write("Genera la orden de trabajo. El sistema cobrara los insumos, descontara el stock y sumara la mano de obra a la nomina del tecnico.")

            recetas_actuales = obtener_receta_vehiculo(veh_id_activo)
            mecanicos = obtener_mecanicos_activos(user_id)

            if not recetas_actuales.empty:
                dict_mec = {m[1]: m[0] for m in mecanicos} if mecanicos else {}

                total_insumos = float((recetas_actuales['precio_venta'] * recetas_actuales['cantidad']).sum())

                st.write("**Insumos a Despachar:**")
                for _, r in recetas_actuales.iterrows():
                    subtotal_item = float(r['precio_venta']) * int(r['cantidad'])
                    st.write(f"- {r['nombre_producto']} (x{r['cantidad']}) - {formato_cop(subtotal_item)}")

                st.markdown("---")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    mec_sel = st.selectbox("Tecnico a cargo", options=list(dict_mec.keys())) if dict_mec else None
                with col_d2:
                    valor_mo = st.number_input("Valor Mano de Obra ($)", min_value=0.0, value=30000.0, step=5000.0)

                nuevo_km = st.number_input("Kilometraje de Ingreso", min_value=int(veh_info[7] or 0), value=int(veh_info[7] or 0) + 5000, step=500)

                gran_total = float(total_insumos) + float(valor_mo)
                st.markdown(f"### Total Orden: {formato_cop(gran_total)}")

                if st.button("Ejecutar y Crear Orden", type="primary", width='stretch'):
                    if not mec_sel:
                        st.error("Registra un mecanico en el Directorio primero.")
                    else:
                        try:
                            with engine.begin() as conn_gen:
                                is_sqlite = "sqlite" in str(conn_gen.engine.url)
                                numero_orden = obtener_siguiente_numero_orden(conn_gen, user_id)

                                if is_sqlite:
                                    cur = conn_gen.execute(text("INSERT INTO Hojas_Trabajo (usuario_id, numero_orden, placa, empresa_id, estado) VALUES (:uid, :numero_orden, :placa, :eid, 'Facturado')"), {"uid": user_id, "numero_orden": numero_orden, "placa": veh_info[3], "eid": veh_info[2]})
                                    nueva_hoja_id = cur.lastrowid
                                else:
                                    res = conn_gen.execute(text("INSERT INTO Hojas_Trabajo (usuario_id, numero_orden, placa, empresa_id, estado) VALUES (:uid, :numero_orden, :placa, :eid, 'Facturado') RETURNING id"), {"uid": user_id, "numero_orden": numero_orden, "placa": veh_info[3], "eid": veh_info[2]})
                                    nueva_hoja_id = res.scalar()

                                for _, r in recetas_actuales.iterrows():
                                    pvp_item = float(r['precio_venta']) * int(r['cantidad'])
                                    conn_gen.execute(
                                        text("INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, precio_venta) VALUES (:hid, 'Repuesto', :desc, :pvp)"),
                                        {"hid": nueva_hoja_id, "desc": f"{r['nombre_producto']} (x{r['cantidad']})", "pvp": pvp_item}
                                    )
                                    conn_gen.execute(text("UPDATE Inventario SET stock_actual = stock_actual - :cant WHERE id = :inv_id"), {"cant": int(r['cantidad']), "inv_id": int(r['inv_id'])})

                                conn_gen.execute(
                                    text("INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, precio_venta) VALUES (:hid, 'Mano de Obra', :desc, :mid, :pvp)"),
                                    {"hid": nueva_hoja_id, "desc": f"Servicio Cambio de Aceite", "mid": dict_mec[mec_sel], "pvp": float(valor_mo)}
                                )

                                hoy = datetime.today().date()
                                proxima = hoy + timedelta(days=int((veh_info[8] or 3) * 30))
                                conn_gen.execute(
                                    text("UPDATE Vehiculos_Flota SET fecha_ultimo_servicio = :f_ult, fecha_proximo_servicio = :f_prox, kilometraje_actual = :km WHERE id = :vid"),
                                    {"f_ult": hoy.strftime('%Y-%m-%d'), "f_prox": proxima.strftime('%Y-%m-%d'), "km": int(nuevo_km), "vid": veh_id_activo}
                                )

                            # La orden queda directamente en estado 'Facturado', así que
                            # no aparece en Tablero/Dashboard/Nómina (todos filtran
                            # estado != 'Facturado'). Solo hace falta refrescar el
                            # inventario (se descontó stock) y los datos del vehículo
                            # (fechas y kilometraje actualizados).
                            invalidar_cache_inventario()
                            invalidar_cache_flota()
                            obtener_metricas_financieras.clear()
                            st.success(f"Orden #{numero_orden} creada. Repuestos descontados y mano de obra sumada a {mec_sel}.")
                            st.rerun()
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "crear la orden"))
            else:
                st.warning("Configura los insumos de este vehiculo en la pestaña anterior para poder despachar.")
    else:
        st.info("No hay vehiculos registrados. Usa el formulario superior para agregar el primero.")
