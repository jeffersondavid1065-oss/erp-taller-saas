import streamlit as st
import pandas as pd
import os
import math
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Expediente y Edición", page_icon="📑", layout="wide")

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

st.title("📑 Expediente de Orden y Facturación")
st.markdown(f"Gestión de órdenes para: **{st.session_state.nombre_taller}**")
st.markdown("---")

def obtener_mecanicos():
    with engine.connect() as conn:
        query = text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid")
        datos = conn.execute(query, {"uid": user_id}).fetchall()
    return {f"{m[1]}": m[0] for m in datos}

st.subheader("📋 Historial de Órdenes por Fecha")

col_f1, col_f2 = st.columns([2, 2])
with col_f1:
    hoy = datetime.today()
    hace_7_dias = hoy - timedelta(days=7)
    fechas_filtro = st.date_input("Selecciona el rango de fechas a facturar", [hace_7_dias, hoy])

if len(fechas_filtro) == 2:
    fecha_inicio, fecha_fin = fechas_filtro
    fecha_fin_extendida = fecha_fin + timedelta(days=1) 

    with engine.connect() as conn:
        # Contamos las órdenes de este taller en el rango de fechas
        query_count = text('''
            SELECT COUNT(*) FROM Hojas_Trabajo 
            WHERE usuario_id = :uid AND fecha_ingreso >= :f_ini AND fecha_ingreso < :f_fin
        ''')
        total_registros = conn.execute(query_count, {"uid": user_id, "f_ini": fecha_inicio, "f_fin": fecha_fin_extendida}).scalar()

    if total_registros > 0:
        REGISTROS_POR_PAGINA = 20
        total_paginas = math.ceil(total_registros / REGISTROS_POR_PAGINA)
        
        with col_f2:
            if total_paginas > 1:
                pagina_actual = st.number_input("Ir a la Página", min_value=1, max_value=total_paginas, value=1)
            else:
                pagina_actual = 1
                st.text("Página 1 de 1")
        
        offset = (pagina_actual - 1) * REGISTROS_POR_PAGINA
        
        # Traemos las órdenes conectadas a Supabase
        query_lista = text('''
            SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", 
                   h.placa as "Placa", e.razon_social as "Empresa", h.estado as "Estado"
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            WHERE h.usuario_id = :uid AND h.fecha_ingreso >= :f_ini AND h.fecha_ingreso < :f_fin
            ORDER BY h.id DESC
            LIMIT :limit OFFSET :offset
        ''')
        
        with engine.connect() as conn:
            df_lista = pd.read_sql_query(
                query_lista, 
                con=conn, 
                params={
                    "uid": user_id, 
                    "f_ini": fecha_inicio, 
                    "f_fin": fecha_fin_extendida, 
                    "limit": REGISTROS_POR_PAGINA, 
                    "offset": offset
                }
            )
        
        st.dataframe(df_lista, use_container_width=True, hide_index=True)
    else:
        st.info("No hay órdenes registradas en el rango de fechas seleccionado.")
else:
    st.warning("Por favor selecciona un rango de fechas válido.")

st.markdown("---")

st.subheader("🔍 Abrir Expediente Específico")
st.markdown("Mira el N° de Orden en la tabla de arriba y escríbelo aquí para ver sus detalles, editar o facturar.")

orden_busqueda = st.text_input("Ingresa el NÚMERO DE ORDEN (Ej: 1, 2, 3...)")

if orden_busqueda:
    if orden_busqueda.isdigit(): 
        orden_id = int(orden_busqueda)
        
        with engine.connect() as conn:
            query_vehiculo = text('''
                SELECT h.id, h.placa, h.estado, h.fecha_ingreso, e.razon_social, e.nit 
                FROM Hojas_Trabajo h
                JOIN Empresas_Clientes e ON h.empresa_id = e.id
                WHERE h.id = :oid AND h.usuario_id = :uid
            ''')
            vehiculo = conn.execute(query_vehiculo, {"oid": orden_id, "uid": user_id}).fetchone()
        
        if not vehiculo:
            st.warning(f"No se encontró ninguna orden con el número #{orden_id} en tu taller.")
        else:
            hoja_id, placa, estado_actual, fecha, cliente, nit = vehiculo
            
            st.markdown(f"### Expediente de Orden #{hoja_id} | Placa: {placa}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Cliente", cliente)
            col2.metric("NIT", nit)
            col3.metric("Estado Actual", estado_actual)
            
            with engine.connect() as conn:
                df_trabajos = pd.read_sql_query(
                    text('''
                        SELECT d.id, d.tipo_item, d.descripcion, m.nombre as mecanico, 
                               d.costo_compra, d.precio_venta 
                        FROM Detalles_Orden d
                        LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
                        WHERE d.hoja_id = :hid
                    '''), 
                    con=conn, 
                    params={"hid": hoja_id}
                )
            
            tab_factura, tab_editar = st.tabs(["🧾 Ver y Facturar", "✏️ Editar Orden (Corregir / Agregar)"])
            
            with tab_factura:
                if not df_trabajos.empty:
                    df_mostrar = df_trabajos[['tipo_item', 'descripcion', 'mecanico', 'precio_venta']].copy()
                    df_mostrar.columns = ['Tipo', 'Descripción', 'Técnico', 'Cobro al Cliente']
                    st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
                    
                    gran_total = df_trabajos['precio_venta'].sum()
                    st.success(f"**Total a cobrar al cliente:** ${gran_total:,.2f}")
                    
                    if estado_actual == "Listo para facturar":
                        texto_factura = f"ORDEN DE SERVICIO: #{hoja_id}\nCLIENTE: {cliente}\nNIT: {nit}\nPLACA: {placa}\n\nSERVICIOS Y REPUESTOS:\n"
                        for index, row in df_trabajos.iterrows():
                            texto_factura += f"- {row['tipo_item']}: {row['descripcion']} (${row['precio_venta']:,.0f})\n"
                        texto_factura += f"\nGRAN TOTAL: ${gran_total:,.0f}"
                        st.code(texto_factura, language="text")
                    else:
                        st.info("ℹ️ Cambia el estado a 'Listo para facturar' en la pestaña de Edición para generar el bloque de facturación.")
                else:
                    st.info("No hay trabajos registrados para esta orden todavía.")

            with tab_editar:
                st.markdown("### 1. Cambiar Estado del Vehículo")
                col_est1, col_est2 = st.columns([2, 1])
                with col_est1:
                    estados_disponibles = ["Cotizar", "En revisión", "Esperando repuestos", "En reparación", "Listo para facturar", "Facturado"]
                    indice_actual = estados_disponibles.index(estado_actual) if estado_actual in estados_disponibles else 0
                    nuevo_estado = st.selectbox("Selecciona el nuevo estado", estados_disponibles, index=indice_actual)
                with col_est2:
                    st.write("") 
                    if st.button("🔄 Guardar Cambio de Estado"):
                        try:
                            with engine.begin() as conn_est:
                                conn_est.execute(
                                    text("UPDATE Hojas_Trabajo SET estado = :est WHERE id = :hid"),
                                    {"est": nuevo_estado, "hid": hoja_id}
                                )
                            st.success("Estado actualizado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                
                st.markdown("---")
                st.markdown("### 2. Corregir o Eliminar Ítems")
                if not df_trabajos.empty:
                    for index, row in df_trabajos.iterrows():
                        with st.container(border=True):
                            col_e1, col_e2, col_e3 = st.columns([4, 2, 1])
                            with col_e1:
                                st.write(f"**{row['tipo_item']}**: {row['descripcion']}")
                            with col_e2:
                                st.write(f"Valor: ${row['precio_venta']:,.0f}")
                            with col_e3:
                                if st.button("🗑️ Eliminar", key=f"del_{row['id']}"):
                                    try:
                                        with engine.begin() as conn_del:
                                            conn_del.execute(
                                                text("DELETE FROM Detalles_Orden WHERE id = :did"),
                                                {"did": row['id']}
                                            )
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error al eliminar: {e}")
                else:
                    st.warning("No hay ítems para corregir.")

                st.markdown("---")
                st.markdown("### 3. Agregar Nuevos Ítems a esta Orden")
                dict_mecanicos = obtener_mecanicos()
                
                with st.expander("➕ Despliega para agregar un Trabajo o Repuesto nuevo"):
                    tab_mo, tab_rep = st.tabs(["🔧 Mano de Obra", "📦 Repuesto"])
                    
                    with tab_mo:
                        desc_mo = st.text_input("Descripción", key="e_desc_mo")
                        mec_sel = st.selectbox("Mecánico", options=list(dict_mecanicos.keys()), key="e_mec_mo") if dict_mecanicos else None
                        venta_mo = st.number_input("Cobro Cliente ($)", min_value=0, step=5000, key="e_venta_mo")
                        if st.button("💾 Guardar Trabajo"):
                            if desc_mo and venta_mo > 0 and mec_sel:
                                try:
                                    with engine.begin() as conn_mo:
                                        conn_mo.execute(
                                            text('''
                                                INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, precio_venta)
                                                VALUES (:hid, 'Mano de Obra', :desc, :mid, :pvp)
                                            '''),
                                            {"hid": hoja_id, "desc": desc_mo, "mid": dict_mecanicos[mec_sel], "pvp": float(venta_mo)}
                                        )
                                    st.success("¡Trabajo agregado con éxito!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                            else:
                                st.error("Completa la descripción, el precio y asegúrate de tener mecánicos registrados.")
                            
                    with tab_rep:
                        desc_rep = st.text_input("Nombre Repuesto", key="e_desc_rep")
                        costo_rep = st.number_input("Costo Compra ($)", min_value=0, step=1000, key="e_costo_rep")
                        venta_rep = st.number_input("Precio Venta ($)", min_value=0, step=1000, key="e_venta_rep")
                        if st.button("💾 Guardar Repuesto"):
                            if desc_rep and venta_rep > 0:
                                try:
                                    with engine.begin() as conn_rep:
                                        conn_rep.execute(
                                            text('''
                                                INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, costo_compra, precio_venta)
                                                VALUES (:hid, 'Repuesto', :desc, :costo, :pvp)
                                            '''),
                                            {"hid": hoja_id, "desc": desc_rep, "costo": float(costo_rep), "pvp": float(venta_rep)}
                                        )
                                    st.success("¡Repuesto agregado con éxito!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                            else:
                                st.error("Llenar descripción y precio de venta.")
    else:
        st.error("Por favor, ingresa solo números (Ej: 1, 2, 3...)")
