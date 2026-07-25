import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Directorio y CRM", layout="wide")

# ==========================================
# ESTILOS CSS: OCULTAR BARRA Y ANIMACIONES
# ==========================================
st.markdown("""
    <style>
    /* Ocultar toda la esquina superior derecha (Fork, GitHub, Menu) */
    [data-testid="stHeader"] {
        display: none !important;
    }

    /* Animación de entrada */
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

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("Directorio y Expediente de Clientes")
st.markdown(f"Administración de clientes, flotas y personal para: **{st.session_state.nombre_taller}**")
st.markdown("---")

tab_empresas, tab_mecanicos = st.tabs(["Empresas y Flotas", "Equipo de Mecánicos"])

# ==========================================
# PESTAÑA 1: GESTIÓN DE EMPRESAS Y CRM
# ==========================================
with tab_empresas:
    
    with st.expander("Registrar una nueva empresa o cliente", expanded=False):
        with st.form("form_nueva_empresa", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                razon_social = st.text_input("Razón Social o Nombre del Cliente")
                nit = st.text_input("NIT o Cédula (Sin puntos)")
            with col2:
                telefono = st.text_input("Teléfono de Contacto")
                email = st.text_input("Correo Electrónico")
            
            submit_empresa = st.form_submit_button("Guardar Empresa", type="primary")
            
            if submit_empresa:
                if razon_social and nit:
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text('''
                                    INSERT INTO Empresas_Clientes (usuario_id, razon_social, nit, telefono, email) 
                                    VALUES (:uid, :razon, :nit, :tel, :email)
                                '''),
                                {
                                    "uid": user_id, 
                                    "razon": razon_social, 
                                    "nit": nit, 
                                    "tel": telefono, 
                                    "email": email
                                }
                            )
                        st.success(f"La empresa {razon_social} fue registrada con éxito en el sistema.")
                        st.rerun()
                    except Exception as e:
                        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                            st.error("Error: Ya existe una empresa registrada con ese mismo NIT en el taller.")
                        else:
                            st.error(f"Error al registrar: {e}")
                else:
                    st.warning("La Razón Social y el NIT son campos obligatorios.")

    st.markdown("---")
    
    # ==========================================
    # BUSCADOR DINÁMICO CON OPCIÓN VACÍA INICIAL
    # ==========================================
    st.subheader("Buscador y Gestión de Clientes / Empresas")
    
    with engine.connect() as conn:
        empresas_df = pd.read_sql_query(
            text("SELECT id, razon_social, nit, telefono, email FROM Empresas_Clientes WHERE usuario_id = :uid ORDER BY razon_social ASC"), 
            con=conn, 
            params={"uid": user_id}
        )

    if not empresas_df.empty:
        # Creamos el diccionario y añadimos una opción vacía al inicio
        dict_empresas = {f"{row['razon_social']} (NIT/CC: {row['nit']})": row['id'] for index, row in empresas_df.iterrows()}
        opciones_select = ["-- Selecciona o busca una empresa --"] + list(dict_empresas.keys())
        
        empresa_seleccionada_str = st.selectbox(
            "Escribe o busca la empresa / cliente:", 
            options=opciones_select,
            help="Empieza a escribir el nombre para filtrar automáticamente."
        )
        
        # Si el usuario no ha seleccionado ninguna empresa real, detenemos el despliegue aquí
        if empresa_seleccionada_str == "-- Selecciona o busca una empresa --":
            st.info("Selecciona o busca una empresa en la casilla superior para ver su información y su historial.")
        else:
            empresa_id_activo = dict_empresas[empresa_seleccionada_str]
            empresa_info = empresas_df[empresas_df['id'] == empresa_id_activo].iloc[0]
            
            # Tarjeta desplegada con opciones de Editar y Eliminar
            with st.container(border=True):
                col_card1, col_card2, col_card_btn1, col_card_btn2 = st.columns([3, 2, 1, 1])
                with col_card1:
                    st.markdown(f"#### {empresa_info['razon_social']}")
                    st.caption(f"**NIT / Cédula:** {empresa_info['nit']}")
                with col_card2:
                    st.markdown(f"**Teléfono:** {empresa_info['telefono'] or 'No registrado'}")
                    st.markdown(f"**Email:** {empresa_info['email'] or 'No registrado'}")
                with col_card_btn1:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("Editar", key=f"btn_edit_{empresa_info['id']}", use_container_width=True):
                        st.session_state[f"edit_emp_mode_{empresa_info['id']}"] = True
                        st.session_state[f"delete_emp_confirm_{empresa_info['id']}"] = False
                with col_card_btn2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("Eliminar", key=f"btn_del_emp_{empresa_info['id']}", use_container_width=True):
                        st.session_state[f"delete_emp_confirm_{empresa_info['id']}"] = True
                        st.session_state[f"edit_emp_mode_{empresa_info['id']}"] = False

                # Confirmación de eliminación
                if st.session_state.get(f"delete_emp_confirm_{empresa_info['id']}", False):
                    st.warning(f"¿Estás seguro de eliminar a **{empresa_info['razon_social']}**? Esta acción no se puede deshacer si tiene registros.")
                    col_conf1, col_conf2 = st.columns(2)
                    with col_conf1:
                        if st.button("Sí, eliminar definitivamente", key=f"yes_del_emp_{empresa_info['id']}", type="primary"):
                            try:
                                with engine.begin() as conn_del:
                                    conn_del.execute(
                                        text("DELETE FROM Empresas_Clientes WHERE id = :id AND usuario_id = :uid"),
                                        {"id": empresa_info['id'], "uid": user_id}
                                    )
                                st.session_state[f"delete_emp_confirm_{empresa_info['id']}"] = False
                                st.success("Empresa eliminada con éxito.")
                                st.rerun()
                            except Exception:
                                st.error("No se puede eliminar esta empresa porque tiene órdenes de trabajo o vehículos asociados en el historial.")
                    with col_conf2:
                        if st.button("Cancelar", key=f"no_del_emp_{empresa_info['id']}"):
                            st.session_state[f"delete_emp_confirm_{empresa_info['id']}"] = False
                            st.rerun()

                # Formulario de edición
                if st.session_state.get(f"edit_emp_mode_{empresa_info['id']}", False):
                    st.markdown("---")
                    with st.form(key=f"form_update_emp_{empresa_info['id']}"):
                        st.markdown(f"**Actualizar datos de:** {empresa_info['razon_social']}")
                        upd_razon = st.text_input("Razón Social o Nombre", value=empresa_info['razon_social'])
                        upd_nit = st.text_input("NIT o Cédula", value=empresa_info['nit'])
                        upd_tel = st.text_input("Teléfono", value=empresa_info['telefono'] or "")
                        upd_email = st.text_input("Correo Electrónico", value=empresa_info['email'] or "")
                        
                        col_f1, col_f2 = st.columns(2)
                        with col_f1:
                            guardar_emp = st.form_submit_button("Guardar Cambios", type="primary")
                        with col_f2:
                            cancelar_emp = st.form_submit_button("Cancelar")
                            
                        if guardar_emp:
                            try:
                                with engine.begin() as conn_upd:
                                    conn_upd.execute(
                                        text('''
                                            UPDATE Empresas_Clientes 
                                            SET razon_social = :razon, nit = :nit, telefono = :tel, email = :email 
                                            WHERE id = :id AND usuario_id = :uid
                                        '''),
                                        {
                                            "razon": upd_razon,
                                            "nit": upd_nit,
                                            "tel": upd_tel,
                                            "email": upd_email,
                                            "id": empresa_info['id'],
                                            "uid": user_id
                                        }
                                    )
                                st.session_state[f"edit_emp_mode_{empresa_info['id']}"] = False
                                st.success("Empresa actualizada con éxito.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al actualizar: {e}")
                        if cancelar_emp:
                            st.session_state[f"edit_emp_mode_{empresa_info['id']}"] = False
                            st.rerun()

            st.markdown("---")
            
            # ==========================================
            # HISTORIAL DE TRABAJOS DE LA EMPRESA SELECCIONADA
            # ==========================================
            st.subheader("Historial de Trabajos y Flota")
            
            col_filtro2, col_filtro3 = st.columns([2, 1])
            with col_filtro2:
                hoy = datetime.today()
                hace_un_mes = hoy - timedelta(days=30)
                fechas = st.date_input("Rango de fechas a consultar", [hace_un_mes, hoy], key="fechas_historial")
            with col_filtro3:
                filtro_placa_opcional = st.text_input("Filtrar por Placa (Opcional)").upper().strip()
            
            if len(fechas) == 2:
                fecha_inicio, fecha_fin = fechas
                fecha_fin_extendida = fecha_fin + timedelta(days=1) 
                
                params_query = {
                    "eid": empresa_id_activo, 
                    "uid": user_id, 
                    "f_ini": fecha_inicio.strftime('%Y-%m-%d'), 
                    "f_fin": fecha_fin_extendida.strftime('%Y-%m-%d')
                }
                
                condicion_placa = ""
                if filtro_placa_opcional:
                    condicion_placa = "AND h.placa LIKE :placa"
                    params_query["placa"] = f"%{filtro_placa_opcional}%"

                tipo_vista = st.radio(
                    "Selecciona el tipo de vista:", 
                    ["Vista Resumida (Solo Órdenes)", "Vista Detallada (Ítems y Repuestos)"],
                    horizontal=True,
                    key="radio_vista_hist"
                )

                if "Resumida" in tipo_vista:
                    query_historial = f'''
                        SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", h.placa as "Placa", 
                               SUM(d.precio_venta) as "Total Cobrado", h.estado as "Estado"
                        FROM Hojas_Trabajo h
                        JOIN Detalles_Orden d ON h.id = d.hoja_id
                        WHERE h.empresa_id = :eid AND h.usuario_id = :uid 
                        AND h.fecha_ingreso >= :f_ini AND h.fecha_ingreso < :f_fin {condicion_placa}
                        GROUP BY h.id, h.fecha_ingreso, h.placa, h.estado
                        ORDER BY h.id DESC
                    '''
                else:
                    query_historial = f'''
                        SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", h.placa as "Placa", 
                               d.tipo_item as "Tipo", d.descripcion as "Detalle", 
                               d.precio_venta as "Cobrado", h.estado as "Estado"
                        FROM Hojas_Trabajo h
                        JOIN Detalles_Orden d ON h.id = d.hoja_id
                        WHERE h.empresa_id = :eid AND h.usuario_id = :uid 
                        AND h.fecha_ingreso >= :f_ini AND h.fecha_ingreso < :f_fin {condicion_placa}
                        ORDER BY h.id DESC
                    '''
                    
                with engine.connect() as conn:
                    df_historial = pd.read_sql_query(text(query_historial), con=conn, params=params_query)
                
                if not df_historial.empty:
                    columna_suma = 'Total Cobrado' if "Resumida" in tipo_vista else 'Cobrado'
                    total_facturado = df_historial[columna_suma].sum()
                    
                    met1, met2 = st.columns(2)
                    met1.metric("Órdenes / Vehículos Atendidos", len(df_historial) if "Resumida" in tipo_vista else df_historial['N° Orden'].nunique())
                    met2.metric("Total Facturado en el Periodo", formato_cop(total_facturado))
                    
                    st.dataframe(df_historial.style.format({
                        columna_suma: lambda x: formato_cop(x)
                    }), use_container_width=True, hide_index=True)
                    
                    csv = df_historial.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="Descargar Reporte en CSV (Para Excel)",
                        data=csv,
                        file_name=f"Reporte_{empresa_info['razon_social']}_{fecha_inicio}.csv",
                        mime="text/csv",
                    )
                else:
                    st.info("No hay registros que coincidan con la empresa y el filtro de placa en este rango de fechas.")
    else:
        st.info("Aún no tienes empresas registradas. Usa el formulario superior para agregar la primera.")

# ==========================================
# PESTAÑA 2: GESTIÓN DE MECÁNICOS
# ==========================================
with tab_mecanicos:
    col_mec1, col_mec2 = st.columns(2)
    
    with col_mec1:
        st.subheader("Agregar Nuevo Mecánico")
        with st.form("form_nuevo_mecanico", clear_on_submit=True):
            nombre_mec = st.text_input("Nombre Completo")
            doc_mec = st.text_input("Documento de Identidad")
            
            if st.form_submit_button("Contratar / Registrar Mecánico", type="primary"):
                if nombre_mec and doc_mec:
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text('''
                                    INSERT INTO Mecanicos (usuario_id, nombre, documento, estado) 
                                    VALUES (:uid, :nombre, :doc, 'Activo')
                                '''),
                                {"uid": user_id, "nombre": nombre_mec, "doc": doc_mec}
                            )
                        st.success(f"{nombre_mec} ha sido agregado al equipo con éxito.")
                        st.rerun()
                    except Exception as e:
                        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                            st.error("Este documento ya está registrado en el sistema.")
                        else:
                            st.error(f"Error al registrar: {e}")
                else:
                    st.warning("Por favor, completa ambos campos.")
    
    with col_mec2:
        st.subheader("Personal Actual")
        
        with engine.connect() as conn:
            mecanicos_db = pd.read_sql_query(
                text("SELECT id, nombre, documento, estado FROM Mecanicos WHERE usuario_id = :uid"), 
                con=conn, 
                params={"uid": user_id}
            )
        
        if not mecanicos_db.empty:
            for index, row in mecanicos_db.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['nombre']}**")
                    st.caption(f"Documento: {row['documento']} | Estado: **{row['estado']}**")
                    
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        if st.button("Editar", key=f"btn_edit_mec_{row['id']}", use_container_width=True):
                            st.session_state[f"edit_mode_{row['id']}"] = True
                    with col_m2:
                        if st.button("Eliminar", key=f"btn_del_mec_{row['id']}", use_container_width=True):
                            try:
                                with engine.begin() as conn_del:
                                    conn_del.execute(
                                        text("DELETE FROM Mecanicos WHERE id = :id AND usuario_id = :uid"),
                                        {"id": row['id'], "uid": user_id}
                                    )
                                st.success("Mecánico eliminado.")
                                st.rerun()
                            except Exception:
                                st.error("No se puede eliminar: tiene trabajos asociados en órdenes de servicio.")
                    
                    if st.session_state.get(f"edit_mode_{row['id']}", False):
                        with st.form(key=f"form_update_mec_{row['id']}"):
                            nuevo_nombre = st.text_input("Nombre", value=row['nombre'])
                            nuevo_doc = st.text_input("Documento", value=row['documento'])
                            nuevo_estado = st.selectbox("Estado", ["Activo", "Inactivo"], index=0 if row['estado'] == 'Activo' else 1)
                            
                            col_f1, col_f2 = st.columns(2)
                            with col_f1:
                                guardar = st.form_submit_button("Guardar", type="primary")
                            with col_f2:
                                cancelar = st.form_submit_button("Cancelar")
                                
                            if guardar:
                                try:
                                    with engine.begin() as conn_upd:
                                        conn_upd.execute(
                                            text('''
                                                UPDATE Mecanicos 
                                                SET nombre = :nombre, documento = :doc, estado = :estado 
                                                WHERE id = :id AND usuario_id = :uid
                                            '''),
                                            {
                                                "nombre": nuevo_nombre, 
                                                "doc": nuevo_doc, 
                                                "estado": nuevo_estado, 
                                                "id": row['id'], 
                                                "uid": user_id
                                            }
                                        )
                                    st.session_state[f"edit_mode_{row['id']}"] = False
                                    st.success("Registro actualizado con éxito.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar: {e}")
                            if cancelar:
                                st.session_state[f"edit_mode_{row['id']}"] = False
                                st.rerun()
        else:
            st.info("No hay mecánicos registrados en el sistema.")
