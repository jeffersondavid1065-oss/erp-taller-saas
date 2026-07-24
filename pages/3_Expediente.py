import streamlit as st
import sqlite3
import pandas as pd
import os
import math
from datetime import datetime, timedelta

st.set_page_config(page_title="Expediente y Edición", page_icon="📑", layout="wide")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

user_id = st.session_state.user_id

st.title("📑 Expediente de Orden y Facturación")
st.markdown(f"Gestión de órdenes para: **{st.session_state.nombre_taller}**")
st.markdown("---")

def obtener_mecanicos():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Solo los mecánicos de este taller
    cursor.execute("SELECT id, nombre FROM Mecanicos WHERE usuario_id = ?", (user_id,))
    datos = cursor.fetchall()
    conn.close()
    return {f"{m[1]}": m[0] for m in datos}

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

st.subheader("📋 Historial de Órdenes por Fecha")

col_f1, col_f2 = st.columns([2, 2])
with col_f1:
    hoy = datetime.today()
    hace_7_dias = hoy - timedelta(days=7)
    fechas_filtro = st.date_input("Selecciona el rango de fechas a facturar", [hace_7_dias, hoy])

if len(fechas_filtro) == 2:
    fecha_inicio, fecha_fin = fechas_filtro
    fecha_fin_extendida = fecha_fin + timedelta(days=1) 

    # Contamos las órdenes de este taller en el rango de fechas
    cursor.execute('''
        SELECT COUNT(*) FROM Hojas_Trabajo 
        WHERE usuario_id = ? AND fecha_ingreso >= ? AND fecha_ingreso < ?
    ''', (user_id, fecha_inicio, fecha_fin_extendida))
    total_registros = cursor.fetchone()[0]

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
        
        # Traemos solo las órdenes de este usuario_id
        query_lista = '''
            SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", 
                   h.placa as "Placa", e.razon_social as "Empresa", h.estado as "Estado"
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            WHERE h.usuario_id = ? AND h.fecha_ingreso >= ? AND h.fecha_ingreso < ?
            ORDER BY h.id DESC
            LIMIT ? OFFSET ?
        '''
        df_lista = pd.read_sql_query(query_lista, conn, params=(user_id, fecha_inicio, fecha_fin_extendida, REGISTROS_POR_PAGINA, offset))
        
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
        
        # Validamos que la orden pertenezca al taller logueado
        query_vehiculo = '''
            SELECT h.id, h.placa, h.estado, h.fecha_ingreso, e.razon_social, e.nit 
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            WHERE h.id = ? AND h.usuario_id = ?
        '''
        cursor.execute(query_vehiculo, (orden_id, user_id))
        vehiculo = cursor.fetchone()
        
        if not vehiculo:
            st.warning(f"No se encontró ninguna orden con el número #{orden_id} en tu taller.")
        else:
            hoja_id, placa, estado_actual, fecha, cliente, nit = vehiculo
            
            st.markdown(f"### Expediente de Orden #{hoja_id} | Placa: {placa}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Cliente", cliente)
            col2.metric("NIT", nit)
            col3.metric("Estado Actual", estado_actual)
            
            df_trabajos = pd.read_sql_query('''
                SELECT d.id, d.tipo_item, d.descripcion, m.nombre as mecanico, 
                       d.costo_compra, d.precio_venta 
                FROM Detalles_Orden d
                LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
                WHERE d.hoja_id = ?
            ''', conn, params=(hoja_id,))
            
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
                        c = conn.cursor()
                        c.execute("UPDATE Hojas_Trabajo SET estado = ? WHERE id = ?", (nuevo_estado, hoja_id))
                        conn.commit()
                        st.success("Estado actualizado.")
                        st.rerun()
                
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
                                    c = conn.cursor()
                                    c.execute("DELETE FROM Detalles_Orden WHERE id = ?", (row['id'],))
                                    conn.commit()
                                    st.rerun()
                else:
                    st.warning("No hay ítems para corregir.")

                st.markdown("---")
                st.markdown("### 3. Agregar Nuevos Ítems a esta Orden")
                dict_mecanicos = obtener_mecanicos()
                
                with st.expander("➕ Despliega para agregar un Trabajo o Repuesto nuevo"):
                    tab_mo, tab_rep = st.tabs(["🔧 Mano de Obra", "📦 Repuesto"])
                    
                    with tab_mo:
                        desc_mo = st.text_input("Descripción", key="e_desc_mo")
                        mec_sel = st.selectbox("Mecánico", options=list(dict_mecanicos.keys()), key="e_mec_mo")
                        venta_mo = st.number_input("Cobro Cliente ($)", min_value=0, step=5000, key="e_venta_mo")
                        if st.button("💾 Guardar Trabajo"):
                            if desc_mo and venta_mo > 0:
                                c = conn.cursor()
                                c.execute('''INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, precio_venta)
                                             VALUES (?, 'Mano de Obra', ?, ?, ?)''', 
                                          (hoja_id, desc_mo, dict_mecanicos[mec_sel], venta_mo))
                                conn.commit()
                                st.rerun()
                                
                    with tab_rep:
                        desc_rep = st.text_input("Nombre Repuesto", key="e_desc_rep")
                        costo_rep = st.number_input("Costo Compra ($)", min_value=0, step=1000, key="e_costo_rep")
                        venta_rep = st.number_input("Precio Venta ($)", min_value=0, step=1000, key="e_venta_rep")
                        if st.button("💾 Guardar Repuesto"):
                            if desc_rep and venta_rep > 0:
                                c = conn.cursor()
                                c.execute('''INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, costo_compra, precio_venta)
                                             VALUES (?, 'Repuesto', ?, ?, ?)''', 
                                          (hoja_id, desc_rep, costo_rep, venta_rep))
                                conn.commit()
                                st.rerun()
    else:
        st.error("Por favor, ingresa solo números (Ej: 1, 2, 3...)")

conn.close()