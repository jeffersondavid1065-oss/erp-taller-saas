import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Nómina y Comisiones", page_icon="💰", layout="wide")

# Validación de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("💰 Liquidación de Nómina Dinámica")
st.markdown(f"Auditoría de comisiones para: **{st.session_state.nombre_taller}**")
st.markdown("---")

# ==========================================
# 1. MÓDULO DE AUDITORÍA Y EDICIÓN RÁPIDA
# ==========================================
st.subheader("🛠️ Auditoría de Trabajos Activos")
st.info("💡 Haz doble clic en la **Descripción** o el **Precio** para editarlos. Luego presiona el botón Guardar.")

with engine.connect() as conn:
    query_trabajos = text('''
        SELECT 
            d.id as detalle_id, 
            h.id as orden_nro,
            h.placa, 
            m.nombre as mecanico, 
            d.tipo_item,
            d.descripcion, 
            d.precio_venta 
        FROM Detalles_Orden d
        JOIN Hojas_Trabajo h ON d.hoja_id = h.id
        LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
        WHERE h.usuario_id = :uid AND h.estado != 'Facturado'
        ORDER BY h.fecha_ingreso DESC
    ''')
    df_trabajos = pd.read_sql_query(query_trabajos, con=conn, params={"uid": user_id})

if not df_trabajos.empty:
    df_editado = st.data_editor(
        df_trabajos,
        hide_index=True,
        use_container_width=True,
        disabled=["detalle_id", "orden_nro", "placa", "mecanico", "tipo_item"],
        column_config={
            "detalle_id": None, 
            "orden_nro": "N° Orden",
            "placa": "Placa",
            "mecanico": "Mecánico",
            "tipo_item": "Tipo",
            "descripcion": "Descripción del Trabajo (Editable)",
            "precio_venta": st.column_config.NumberColumn("Precio Venta (Editable)", format="$%d")
        }
    )

    if st.button("💾 Guardar Cambios en la Base de Datos", type="primary"):
        # Comparamos para guardar solo lo que el usuario editó
        cambios = df_editado.compare(df_trabajos)
        if not cambios.empty:
            try:
                with engine.begin() as conn_update:
                    for index, row in df_editado.iterrows():
                        desc_orig = df_trabajos.loc[index, 'descripcion']
                        precio_orig = df_trabajos.loc[index, 'precio_venta']
                        
                        # Si la fila tuvo cambios, la actualizamos en Supabase
                        if row['descripcion'] != desc_orig or row['precio_venta'] != precio_orig:
                            conn_update.execute(
                                text('''
                                    UPDATE Detalles_Orden 
                                    SET descripcion = :desc, precio_venta = :precio 
                                    WHERE id = :id
                                '''),
                                {"desc": row['descripcion'], "precio": float(row['precio_venta']), "id": int(row['detalle_id'])}
                            )
                st.success("✅ ¡Cambios guardados con éxito!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")
        else:
            st.warning("No se detectaron cambios para guardar.")
else:
    st.info("No hay trabajos pendientes de facturación para auditar en este momento.")

st.markdown("---")

# ==========================================
# 2. LIQUIDACIÓN DE NÓMINA ORIGINAL
# ==========================================
def obtener_mecanicos():
    with engine.connect() as conn:
        query = text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid")
        datos = conn.execute(query, {"uid": user_id}).fetchall()
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
        
        query_nomina = text('''
            SELECT h.id as orden_id, h.placa, date(h.fecha_ingreso) as fecha, 
                   d.descripcion as descripcion_trabajo, 
                   d.precio_venta as valor_mano_obra
            FROM Detalles_Orden d
            JOIN Hojas_Trabajo h ON d.hoja_id = h.id
            WHERE d.mecanico_id = :mid 
            AND d.tipo_item = 'Mano de Obra'
            AND h.usuario_id = :uid
            AND h.fecha_ingreso >= :f_inicio AND h.fecha_ingreso < :f_fin
            ORDER BY h.fecha_ingreso DESC
        ''')
        
        with engine.connect() as conn:
            df_nomina = pd.read_sql_query(
                query_nomina, 
                conn, 
                params={
                    "mid": mecanico_id, 
                    "uid": user_id, 
                    "f_inicio": fecha_inicio.strftime('%Y-%m-%d'), 
                    "f_fin": fecha_fin_extendida.strftime('%Y-%m-%d')
                }
            )
        
        st.markdown("---")
        
        if not df_nomina.empty:
            # Cálculo modificado de comisión utilizando el porcentaje exacto en base a la línea original que corregimos antes
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
