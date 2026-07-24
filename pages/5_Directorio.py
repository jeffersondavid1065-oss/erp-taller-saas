import streamlit as st
import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="Directorio y CRM", page_icon="📁", layout="wide")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

user_id = st.session_state.user_id

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("📁 Directorio y Expediente de Clientes")
st.markdown(f"Administración de clientes, flotas y personal para: **{st.session_state.nombre_taller}**")
st.markdown("---")

tab_empresas, tab_mecanicos = st.tabs(["🏢 Empresas y Flotas", "👨‍🔧 Equipo de Mecánicos"])

# ==========================================
# PESTAÑA 1: GESTIÓN DE EMPRESAS Y CRM
# ==========================================
with tab_empresas:
    
    with st.expander("➕ Haz clic aquí para registrar una Nueva Empresa o Cliente", expanded=False):
        with st.form("form_nueva_empresa", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                razon_social = st.text_input("Razón Social o Nombre del Cliente")
                nit = st.text_input("NIT o Cédula (Sin puntos)")
            with col2:
                telefono = st.text_input("Teléfono de Contacto")
                email = st.text_input("Correo Electrónico")
            
            submit_empresa = st.form_submit_button("💾 Guardar Empresa")
            
            if submit_empresa:
                if razon_social and nit:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    try:
                        # 🌟 Guardado amarrado al usuario_id del taller actual
                        c.execute('''
                            INSERT INTO Empresas_Clientes (usuario_id, razon_social, nit, telefono, email) 
                            VALUES (?, ?, ?, ?, ?)
                        ''', (user_id, razon_social, nit, telefono, email))
                        conn.commit()
                        st.success(f"✅ ¡La empresa {razon_social} fue registrada con éxito!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("❌ Error: Ya existe una empresa registrada con ese mismo NIT en tu taller.")
                    finally:
                        conn.close()
                else:
                    st.error("⚠️ La Razón Social y el NIT son campos obligatorios.")

    st.markdown("---")
    
    st.subheader("🔍 Historial de Trabajos por Empresa")
    
    conn = sqlite3.connect(DB_PATH)
    # Solo las empresas de este taller
    empresas = pd.read_sql_query("SELECT id, razon_social, nit FROM Empresas_Clientes WHERE usuario_id = ?", conn, params=(user_id,))
    
    if not empresas.empty:
        dict_empresas = {f"{row['razon_social']} (NIT: {row['nit']})": row['id'] for index, row in empresas.iterrows()}
        
        col_filtro1, col_filtro2 = st.columns(2)
        with col_filtro1:
            empresa_seleccionada = st.selectbox("Selecciona la Empresa", options=list(dict_empresas.keys()))
        with col_filtro2:
            hoy = datetime.today()
            hace_un_mes = hoy - timedelta(days=30)
            fechas = st.date_input("Rango de Fechas a consultar", [hace_un_mes, hoy])
        
        if len(fechas) == 2:
            fecha_inicio, fecha_fin = fechas
            fecha_fin_extendida = fecha_fin + timedelta(days=1) 
            empresa_id = dict_empresas[empresa_seleccionada]
            
            st.markdown("---")
            
            tipo_vista = st.radio(
                "Selecciona el tipo de vista:", 
                ["📋 Vista Resumida (Solo Órdenes)", "🔍 Vista Detallada (Ítems y Repuestos)"],
                horizontal=True
            )
            
            if "Resumida" in tipo_vista:
                query_historial = '''
                    SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", h.placa as "Placa", 
                           SUM(d.precio_venta) as "Total Cobrado", h.estado as "Estado"
                    FROM Hojas_Trabajo h
                    JOIN Detalles_Orden d ON h.id = d.hoja_id
                    WHERE h.empresa_id = ? AND h.usuario_id = ? AND h.fecha_ingreso >= ? AND h.fecha_ingreso < ?
                    GROUP BY h.id, h.fecha_ingreso, h.placa, h.estado
                    ORDER BY h.id DESC
                '''
            else:
                query_historial = '''
                    SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", h.placa as "Placa", 
                           d.tipo_item as "Tipo", d.descripcion as "Detalle", 
                           d.precio_venta as "Cobrado", h.estado as "Estado"
                    FROM Hojas_Trabajo h
                    JOIN Detalles_Orden d ON h.id = d.hoja_id
                    WHERE h.empresa_id = ? AND h.usuario_id = ? AND h.fecha_ingreso >= ? AND h.fecha_ingreso < ?
                    ORDER BY h.id DESC
                '''
                
            df_historial = pd.read_sql_query(query_historial, conn, params=(empresa_id, user_id, fecha_inicio, fecha_fin_extendida))
            
            if not df_historial.empty:
                columna_suma = 'Total Cobrado' if "Resumida" in tipo_vista else 'Cobrado'
                total_facturado = df_historial[columna_suma].sum()
                
                st.markdown(f"### Resumen para: {empresa_seleccionada.split(' (')[0]}")
                met1, met2 = st.columns(2)
                met1.metric("Órdenes / Vehículos Atendidos", len(df_historial) if "Resumida" in tipo_vista else df_historial['N° Orden'].nunique())
                met2.metric("Total Facturado en el Periodo", formato_cop(total_facturado))
                
                st.dataframe(df_historial.style.format({
                    columna_suma: lambda x: formato_cop(x)
                }), use_container_width=True, hide_index=True)
                
                csv = df_historial.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Descargar Reporte en CSV (Para Excel)",
                    data=csv,
                    file_name=f"Reporte_{empresa_seleccionada}_{fecha_inicio}.csv",
                    mime="text/csv",
                )
            else:
                st.info("No hay registros para esta empresa en el rango de fechas seleccionado.")
    else:
        st.info("Aún no tienes empresas registradas. Usa el formulario de arriba para agregar la primera.")
    conn.close()

# ==========================================
# PESTAÑA 2: GESTIÓN DE MECÁNICOS
# ==========================================
with tab_mecanicos:
    col_mec1, col_mec2 = st.columns(2)
    
    with col_mec1:
        st.subheader("➕ Agregar Nuevo Mecánico")
        with st.form("form_nuevo_mecanico", clear_on_submit=True):
            nombre_mec = st.text_input("Nombre Completo")
            doc_mec = st.text_input("Documento de Identidad")
            
            if st.form_submit_button("💾 Contratar / Registrar Mecánico"):
                if nombre_mec and doc_mec:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    try:
                        # 🌟 Mecánico amarrado al usuario_id del taller
                        c.execute('''
                            INSERT INTO Mecanicos (usuario_id, nombre, documento, estado) 
                            VALUES (?, ?, ?, 'Activo')
                        ''', (user_id, nombre_mec, doc_mec))
                        conn.commit()
                        st.success(f"✅ ¡{nombre_mec} ha sido agregado a tu equipo!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("❌ Este documento ya está registrado en tu taller.")
                    finally:
                        conn.close()
                else:
                    st.error("Por favor completa ambos campos.")
    
    with col_mec2:
        st.subheader("👥 Personal Actual (Editar / Eliminar)")
        conn = sqlite3.connect(DB_PATH)
        mecanicos_db = pd.read_sql_query("SELECT id, nombre, documento, estado FROM Mecanicos WHERE usuario_id = ?", conn, params=(user_id,))
        conn.close()
        
        if not mecanicos_db.empty:
            for index, row in mecanicos_db.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['nombre']}**")
                    st.caption(f"Doc: {row['documento']} | Estado: **{row['estado']}**")
                    
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        if st.button("✏️ Editar", key=f"btn_edit_mec_{row['id']}"):
                            st.session_state[f"edit_mode_{row['id']}"] = True
                    with col_m2:
                        if st.button("🗑️ Eliminar", key=f"btn_del_mec_{row['id']}"):
                            conn = sqlite3.connect(DB_PATH)
                            c = conn.cursor()
                            try:
                                c.execute("DELETE FROM Mecanicos WHERE id = ? AND usuario_id = ?", (row['id'], user_id))
                                conn.commit()
                                st.success(f"Mecánico eliminado.")
                                st.rerun()
                            except Exception:
                                st.error("⚠️ No se puede eliminar: tiene trabajos asociados en órdenes.")
                            finally:
                                conn.close()
                    
                    if st.session_state.get(f"edit_mode_{row['id']}", False):
                        with st.form(key=f"form_update_mec_{row['id']}"):
                            nuevo_nombre = st.text_input("Nombre", value=row['nombre'])
                            nuevo_doc = st.text_input("Documento", value=row['documento'])
                            nuevo_estado = st.selectbox("Estado", ["Activo", "Inactivo"], index=0 if row['estado'] == 'Activo' else 1)
                            
                            col_f1, col_f2 = st.columns(2)
                            with col_f1:
                                guardar = st.form_submit_button("💾 Guardar")
                            with col_f2:
                                cancelar = st.form_submit_button("❌ Cancelar")
                                
                            if guardar:
                                conn = sqlite3.connect(DB_PATH)
                                c = conn.cursor()
                                c.execute("UPDATE Mecanicos SET nombre = ?, documento = ?, estado = ? WHERE id = ? AND usuario_id = ?", 
                                          (nuevo_nombre, nuevo_doc, nuevo_estado, row['id'], user_id))
                                conn.commit()
                                conn.close()
                                st.session_state[f"edit_mode_{row['id']}"] = False
                                st.success("¡Actualizado con éxito!")
                                st.rerun()
                            if cancelar:
                                st.session_state[f"edit_mode_{row['id']}"] = False
                                st.rerun()
        else:
            st.info("No hay mecánicos registrados en tu taller.")