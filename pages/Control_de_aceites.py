import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Control de Aceites y Flotas", layout="wide")

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
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out; }
    </style>
""", unsafe_allow_html=True)

if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("🛢️ Control de Cambios de Aceite y Flotas")
st.markdown(f"Mantenimiento preventivo e insumos para: **{st.session_state.nombre_taller}**")
st.markdown("---")

tab_agenda, tab_flota = st.tabs(["📅 Agenda y Próximos Servicios", "🚗 Gestión de Vehículos y Filtros"])

# ==========================================
# PESTAÑA 1: AGENDA Y RECORDATORIOS
# ==========================================
with tab_agenda:
    st.subheader("Vehículos con Mantenimiento Próximo o Vencido")
    
    with engine.connect() as conn:
        df_agenda = pd.read_sql_query(
            text("""
                SELECT v.id, v.placa, v.modelo_vehiculo, e.razon_social as empresa, 
                       v.fecha_ultimo_servicio, v.fecha_proximo_servicio, v.kilometraje_actual
                FROM Vehiculos_Flota v
                JOIN Empresas_Clientes e ON v.empresa_id = e.id
                WHERE v.usuario_id = :uid
                ORDER BY v.fecha_proximo_servicio ASC
            """),
            con=conn, params={"uid": user_id}
        )

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
                    st.write(f"**Vehículo:** {row['modelo_vehiculo'] or 'No especificado'}")
                    st.write(f"**Km Actual:** {row['kilometraje_actual']:,}")
                with col_a3:
                    st.write(f"**Último Serv:** {row['fecha_ultimo_servicio'] or 'N/A'}")
                    st.write(f"**Próximo Serv:** {row['fecha_proximo_servicio']}")
                with col_a4:
                    if dias_restantes < 0:
                        st.error(f"⚠️ Vencido hace {abs(dias_restantes)} días")
                    elif dias_restantes <= 10:
                        st.warning(f"⚠️ Toca en {dias_restantes} días")
                    else:
                        st.success(f"✅ Al día (en {dias_restantes} días)")
    else:
        st.info("No hay vehículos registrados en el sistema de flotas todavía.")

# ==========================================
# PESTAÑA 2: GESTIÓN DE VEHÍCULOS Y FILTROS
# ==========================================
with tab_flota:
    with st.expander("Registrar Nuevo Vehículo a una Empresa", expanded=False):
        with engine.connect() as conn:
            empresas = conn.execute(text("SELECT id, razon_social FROM Empresas_Clientes WHERE usuario_id = :uid"), {"uid": user_id}).fetchall()
        
        if empresas:
            dict_emp = {e[1]: e[0] for e in empresas}
            with st.form("form_nuevo_vehiculo", clear_on_submit=True):
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    placa_v = st.text_input("Placa del Vehículo").upper().strip()
                    empresa_sel_v = st.selectbox("Empresa / Propietario", options=list(dict_emp.keys()))
                    modelo_v = st.text_input("Modelo / Marca (Ej: Chevrolet NPR)")
                with col_f2:
                    km_v = st.number_input("Kilometraje Actual", min_value=0, value=50000, step=1000)
                    intervalo_v = st.number_input("Intervalo de Recordatorio (Meses)", min_value=1, value=3, step=1)
                    fecha_ult_v = st.date_input("Fecha del Último Servicio", value=datetime.today())

                if st.form_submit_button("Guardar Vehículo", type="primary"):
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
                            st.success(f"Vehículo {placa_v} registrado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al registrar: {e}")
                    else:
                        st.warning("La placa es obligatoria.")
        else:
            st.info("Primero debes registrar empresas en el Directorio.")

    st.markdown("---")
    
    with engine.connect() as conn:
        vehiculos_db = pd.read_sql_query(text("SELECT v.id, v.placa, v.modelo_vehiculo, e.razon_social FROM Vehiculos_Flota v JOIN Empresas_Clientes e ON v.empresa_id = e.id WHERE v.usuario_id = :uid ORDER BY v.placa ASC"), con=conn, params={"uid": user_id})

    if not vehiculos_db.empty:
        dict_veh = {f"{r['placa']} - {r['modelo_vehiculo']} ({r['razon_social']})": r['id'] for idx, r in vehiculos_db.iterrows()}
        veh_sel_str = st.selectbox("Selecciona un vehículo para configurar o despachar:", options=list(dict_veh.keys()))
        veh_id_activo = int(dict_veh[veh_sel_str])

        with engine.connect() as conn:
            veh_info = conn.execute(text("SELECT * FROM Vehiculos_Flota WHERE id = :vid"), {"vid": veh_id_activo}).fetchone()

        st.info(f"📋 **Placa:** {veh_info[3]} | **Último servicio:** {veh_info[5] or 'Pendiente'} | **Próximo:** {veh_info[6]}")

        tab_receta, tab_despacho = st.tabs(["⚙️ Configurar Filtros e Insumos (Catálogo)", "🚀 Generar Orden de Trabajo (Despachar)"])

        # PESTAÑA: CONFIGURAR RECETA E INVENTARIO
        with tab_receta:
            st.write("Agrega los filtros o aceites que usa este vehículo. Si es un repuesto nuevo, el sistema lo agregará a tu Almacén General automáticamente.")
            
            with engine.connect() as conn:
                recetas_df = pd.read_sql_query(
                    text("""
                        SELECT r.id, i.nombre_producto, r.cantidad, i.precio_venta 
                        FROM Recetas_Vehiculo r
                        JOIN Inventario i ON r.inventario_id = i.id
                        WHERE r.vehiculo_id = :vid
                    """), 
                    con=conn, params={"vid": veh_id_activo}
                )

            if not recetas_df.empty:
                st.dataframe(recetas_df.rename(columns={"nombre_producto": "Insumo / Filtro", "cantidad": "Cant.", "precio_venta": "Precio Unitario"}), hide_index=True, use_container_width=True)
            else:
                st.caption("No hay insumos configurados para este vehículo.")

            with st.form("form_add_receta_inventario", clear_on_submit=True):
                st.markdown("**Agregar Insumo**")
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    item_desc = st.text_input("Nombre del Filtro o Aceite (Ej: Filtro de Aceite W712)")
                    cant_item = st.number_input("Cantidad que usa el carro", min_value=1, value=1, step=1)
                with col_r2:
                    costo_compra = st.number_input("Costo de Compra ($)", min_value=0.0, step=1000.0)
                    precio_venta = st.number_input("Precio de Venta ($)", min_value=0.0, step=1000.0)

                if st.form_submit_button("Guardar en Receta y Almacén", type="primary"):
                    if item_desc:
                        try:
                            with engine.begin() as conn_r:
                                is_sqlite = "sqlite" in str(conn_r.engine.url)
                                # 1. Insertar en Inventario
                                if is_sqlite:
                                    cur = conn_r.execute(
                                        text("INSERT INTO Inventario (usuario_id, nombre_producto, costo_compra, precio_venta, stock_actual) VALUES (:uid, :nom, :costo, :pvp, 0)"),
                                        {"uid": user_id, "nom": item_desc, "costo": costo_compra, "pvp": precio_venta}
                                    )
                                    nuevo_inv_id = cur.lastrowid
                                else:
                                    res = conn_r.execute(
                                        text("INSERT INTO Inventario (usuario_id, nombre_producto, costo_compra, precio_venta, stock_actual) VALUES (:uid, :nom, :costo, :pvp, 0) RETURNING id"),
                                        {"uid": user_id, "nom": item_desc, "costo": costo_compra, "pvp": precio_venta}
                                    )
                                    nuevo_inv_id = res.scalar()
                                
                                # 2. Ligar a la Receta del Vehículo
                                conn_r.execute(
                                    text("INSERT INTO Recetas_Vehiculo (vehiculo_id, inventario_id, cantidad) VALUES (:vid, :iid, :cant)"),
                                    {"vid": veh_id_activo, "iid": nuevo_inv_id, "cant": int(cant_item)}
                                )
                            st.success("Insumo guardado en el almacén y asignado a este vehículo.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        # PESTAÑA: DESPACHO Y ÓRDENES
        with tab_despacho:
            st.write("Genera la orden de trabajo. El sistema cobrará los insumos, descontará el stock y sumará la mano de obra a la nómina del técnico.")

            with engine.connect() as conn:
                recetas_actuales = conn.execute(
                    text("""
                        SELECT i.id as inv_id, i.nombre_producto, r.cantidad, i.precio_venta 
                        FROM Recetas_Vehiculo r
                        JOIN Inventario i ON r.inventario_id = i.id
                        WHERE r.vehiculo_id = :vid
                    """), {"vid": veh_id_activo}
                ).fetchall()
                
                mecanicos = conn.execute(text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid AND estado = 'Activo'"), {"uid": user_id}).fetchall()

            if recetas_actuales:
                dict_mec = {m[1]: m[0] for m in mecanicos} if mecanicos else {}
                
                total_insumos = sum([r[3] * r[2] for r in recetas_actuales])
                st.write("**Insumos a Despachar:**")
                for r in recetas_actuales:
                    st.write(f"- {r[1]} (x{r[2]}) — {formato_cop(r[3] * r[2])}")
                
                st.markdown("---")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    mec_sel = st.selectbox("Técnico a cargo", options=list(dict_mec.keys())) if dict_mec else None
                with col_d2:
                    valor_mo = st.number_input("Valor Mano de Obra ($)", min_value=0.0, value=30000.0, step=5000.0)

                nuevo_km = st.number_input("Kilometraje de Ingreso", min_value=int(veh_info[7] or 0), value=int(veh_info[7] or 0) + 5000, step=500)
                
                st.markdown(f"### Total Orden: {formato_cop(total_insumos + valor_mo)}")

                if st.button("🚀 Ejecutar y Crear Orden", type="primary", use_container_width=True):
                    if not mec_sel:
                        st.error("Registra un mecánico en el Directorio primero.")
                    else:
                        try:
                            with engine.begin() as conn_gen:
                                is_sqlite = "sqlite" in str(conn_gen.engine.url)
                                
                                # 1. Crear Orden (Hoja de Trabajo)
                                if is_sqlite:
                                    cur = conn_gen.execute(text("INSERT INTO Hojas_Trabajo (usuario_id, placa, empresa_id, estado) VALUES (:uid, :placa, :eid, 'Facturado')"), {"uid": user_id, "placa": veh_info[3], "eid": veh_info[2]})
                                    nueva_hoja_id = cur.lastrowid
                                else:
                                    res = conn_gen.execute(text("INSERT INTO Hojas_Trabajo (usuario_id, placa, empresa_id, estado) VALUES (:uid, :placa, :eid, 'Facturado') RETURNING id"), {"uid": user_id, "placa": veh_info[3], "eid": veh_info[2]})
                                    nueva_hoja_id = res.scalar()

                                # 2. Registrar Repuestos y Descontar Inventario
                                for r in recetas_actuales:
                                    # Insertar detalle orden
                                    conn_gen.execute(
                                        text("INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, precio_venta) VALUES (:hid, 'Repuesto', :desc, :pvp)"),
                                        {"hid": nueva_hoja_id, "desc": f"{r[1]} (x{r[2]})", "pvp": float(r[3] * r[2])}
                                    )
                                    # Descontar stock
                                    conn_gen.execute(text("UPDATE Inventario SET stock_actual = stock_actual - :cant WHERE id = :inv_id"), {"cant": r[2], "inv_id": r[0]})

                                # 3. Registrar Mano de Obra (Sincroniza con Nómina)
                                conn_gen.execute(
                                    text("INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, precio_venta) VALUES (:hid, 'Mano de Obra', :desc, :mid, :pvp)"),
                                    {"hid": nueva_hoja_id, "desc": f"Servicio Cambio de Aceite", "mid": dict_mec[mec_sel], "pvp": float(valor_mo)}
                                )

                                # 4. Actualizar fechas
                                hoy = datetime.today().date()
                                proxima = hoy + timedelta(days=int((veh_info[8] or 3) * 30))
                                conn_gen.execute(
                                    text("UPDATE Vehiculos_Flota SET fecha_ultimo_servicio = :f_ult, fecha_proximo_servicio = :f_prox, kilometraje_actual = :km WHERE id = :vid"),
                                    {"f_ult": hoy.strftime('%Y-%m-%d'), "f_prox": proxima.strftime('%Y-%m-%d'), "km": int(nuevo_km), "vid": veh_id_activo}
                                )

                            st.success(f"¡Orden #{nueva_hoja_id} creada! Repuestos descontados y mano de obra sumada a {mec_sel}.")
                        except Exception as e:
                            st.error(f"Error: {e}")
            else:
                st.warning("Configura los filtros de este vehículo en la pestaña anterior para poder despachar.")
