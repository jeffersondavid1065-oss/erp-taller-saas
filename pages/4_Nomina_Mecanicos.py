import streamlit as st
import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="Nómina y Comisiones", page_icon="💰", layout="wide")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

user_id = st.session_state.user_id

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("💰 Liquidación de Nómina Dinámica")
st.markdown(f"Auditoría de comisiones para: **{st.session_state.nombre_taller}**")
st.markdown("---")

def obtener_mecanicos():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Solo los mecánicos del taller actual
    cursor.execute("SELECT id, nombre FROM Mecanicos WHERE usuario_id = ?", (user_id,))
    datos = cursor.fetchall()
    conn.close()
    return datos

mecanicos = obtener_mecanicos()

if not mecanicos:
    st.info("No hay mecánicos registrados en tu taller.")
else:
    dict_mecanicos = {f"{m[1]}": m[0] for m in mecanicos}
    
    st.subheader("Filtros y Parámetros de Liquidación")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        mecanico_sel = st.selectbox("Selecciona el Técnico", options=list(dict_mecanicos.keys()))
    with col2:
        hoy = datetime.today()
        hace_15_dias = hoy - timedelta(days=15)
        fechas = st.date_input("Rango de fechas", [hace_15_dias, hoy])
    with col3:
        porcentaje_pago = st.number_input("Porcentaje a Pagar (%)", min_value=0, max_value=100, value=50, step=5)
        
    if len(fechas) == 2:
        fecha_inicio, fecha_fin = fechas
        fecha_fin_extendida = fecha_fin + timedelta(days=1) 
        mecanico_id = dict_mecanicos[mecanico_sel]
        
        # Consulta filtrada por usuario_id en Hojas_Trabajo
        query_nomina = '''
            SELECT h.id as orden_id, h.placa, date(h.fecha_ingreso) as fecha, 
                   d.descripcion as descripcion_trabajo, 
                   d.precio_venta as valor_mano_obra
            FROM Detalles_Orden d
            JOIN Hojas_Trabajo h ON d.hoja_id = h.id
            WHERE d.mecanico_id = ? 
            AND d.tipo_item = 'Mano de Obra'
            AND h.usuario_id = ?
            AND h.fecha_ingreso >= ? AND h.fecha_ingreso < ?
            ORDER BY h.fecha_ingreso DESC
        '''
        
        conn = sqlite3.connect(DB_PATH)
        df_nomina = pd.read_sql_query(query_nomina, conn, params=(mecanico_id, user_id, fecha_inicio, fecha_fin_extendida))
        conn.close()
        
        st.markdown("---")
        
        if not df_nomina.empty:
            df_nomina['comision_mecanico'] = (df_nomina['valor_mano_obra'] * (porcentaje_pago / 100)).round(2)
            
            total_mo = df_nomina['valor_mano_obra'].sum()
            total_comision = df_nomina['comision_mecanico'].sum()
            
            st.subheader(f"Resumen de Liquidación: {mecanico_sel}")
            met1, met2, met3 = st.columns(3)
            met1.metric("Trabajos Realizados", len(df_nomina))
            met2.metric("Base (Mano de Obra)", formato_cop(total_mo))
            met3.metric(f"Total a Pagar ({porcentaje_pago}%)", formato_cop(total_comision))
            
            st.markdown("#### Detalle de Trabajos para Auditoría")
            df_mostrar = df_nomina.copy()
            df_mostrar.columns = ['N° Orden', 'Placa', 'Fecha de Ingreso', 'Descripción del Trabajo', 'Cobrado al Cliente ($)', 'Comisión del Técnico ($)']
            
            st.dataframe(df_mostrar.style.format({
                'Cobrado al Cliente ($)': lambda x: formato_cop(x),
                'Comisión del Técnico ($)': lambda x: formato_cop(x)
            }), use_container_width=True, hide_index=True)
            
            csv = df_mostrar.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=f"📥 Descargar Soporte de Pago - {mecanico_sel}",
                data=csv,
                file_name=f"Liquidacion_{mecanico_sel}.csv",
                mime="text/csv",
            )
        else:
            st.info(f"No se encontraron trabajos de mano de obra para {mecanico_sel} en este periodo.")