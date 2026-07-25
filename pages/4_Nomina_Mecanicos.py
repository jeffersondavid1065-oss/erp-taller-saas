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
st.markdown(f"Auditoría de comisiones y ajustes para: **{st.session_state.nombre_taller}**")
st.markdown("---")

# ==========================================
# 1. MÓDULO DE AUDITORÍA Y FILTROS AVANZADOS
# ==========================================
st.subheader("🛠️ Auditoría y Corrección de Trabajos")
st.info("💡 Por defecto se muestran los trabajos recientes. Puedes usar los filtros opcionales de abajo para buscar una orden específica por número, placa, fecha, mecánico o empresa.")

# 🌟 Contenedor de Filtros Opcionales para Auditoría
with st.expander("🔍 Filtros de Búsqueda Avanzada (Opcional)", expanded=False):
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        filtro_nro_orden = st.text_input("N° de Orden (Opcional)")
        filtro_placa = st.text_input("Placa del Vehículo (Opcional)").upper().strip()
    with f_col2:
        filtro_empresa = st.text_input("Nombre de Empresa / Cliente (Opcional)")
        
        # Obtenemos lista de mecánicos para el filtro
        with engine.connect() as conn_m:
            mecanicos_filtro = conn_m.execute(text("SELECT nombre FROM Mecanicos WHERE usuario_id = :uid"), {"uid": user_id}).fetchall()
        lista_nombres_mec = ["-- Todos --"] + [m[0] for m in mecanicos_filtro]
        filtro_mecanico_sel = st.selectbox("Mecánico (Opcional)", options=lista_nombres_mec)
    with f_col3:
        activar_filtro_fechas = st.checkbox("Filtrar por Rango de Fechas")
        if activar_filtro_fechas:
            hoy_f = datetime.today()
            hace_30_f = hoy_f - timedelta(days=30)
            rango_auditoria = st.date_input("Rango de Fechas", [hace_30_f, hoy_f])
        else:
            rango_auditoria = None

# Construcción dinámica de la consulta de auditoría basada en filtros opcionales
query_base_sql = '''
    SELECT 
        d.id as detalle_id, 
        h.id as orden_nro,
        h.placa, 
        e.razon_social as empresa,
        m.nombre as mecanico, 
        d.tipo_item,
        d.descripcion, 
        d.precio_venta,
        h.fecha_ingreso
    FROM Detalles_Orden d
    JOIN Hojas_Trabajo h ON d.hoja_id = h.id
    JOIN Empresas_Clientes e ON h.empresa_id = e.id
    LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
    WHERE h.usuario_id = :uid AND h.estado != 'Facturado'
''']

params_auditoria = {"uid": user_id}

if filtro_nro_orden.isdigit():
    query_base_sql.append("AND h.id = :nro_orden")
    params_auditoria["nro_orden"] = int(filtro_nro_orden)

if filtro_placa:
    query_base_sql.append("AND h.placa LIKE :placa")
    params_auditoria["placa"] = f"%{filtro_placa}%"

if filtro_empresa:
    query_base_sql.append("AND e.razon_social LIKE :empresa")
    params_auditoria["empresa"] = f"%{filtro_empresa}%"

if filtro_mecanico_sel != "-- Todos --":
    query_base_sql.append("AND m.nombre = :mecanico_nombre")
    params_auditoria["mecanico_nombre"] = filtro_mecanico_sel

if activar_filtro_fechas and rango_auditoria and len(rango_auditoria) == 2:
    f_ini, f_fin = rango_auditoria
    f_fin_ext = f_fin + timedelta(days=1)
    query_base_sql.append("AND h.fecha_ingreso >= :f_ini AND h.fecha_ingreso < :f_fin")
    params_auditoria["f_ini"] = f_ini.strftime('%Y-%m-%d')
    params_auditoria["f_fin"] = f_fin_ext.strftime('%Y-%m-%d')

# Si no hay filtros estrictos aplicados, limitamos a los últimos 20 trabajos recientes por defecto
if not filtro_nro_orden and not filtro_placa and not filtro_empresa and filtro_mecanico_sel == "-- Todos --" and not activar_filtro_fechas:
    query_final_str = " ".join(query_base_sql) + " ORDER BY h.fecha_ingreso DESC LIMIT 20"
else:
    query_final_str = " ".join(query_base_sql) + " ORDER BY h.fecha_ingreso DESC"

with engine.connect() as conn:
    df_trabajos = pd.read_sql_query(text(query_final_str), con=conn, params=params_auditoria)

if not df_trabajos.empty:
    # Ocultamos la columna auxiliar fecha_ingreso para el editor visual
    df_para_editar = df_trabajos.drop(columns=['fecha_ingreso'])
    
    df_editado = st.data_editor(
        df_para_editar,
        hide_index=True,
        use_container_width=True,
        disabled=["detalle_id", "orden_nro", "placa", "empresa", "mecanico", "tipo_item"],
        column_config={
            "detalle_id": None, 
            "orden_nro": "N° Orden",
            "placa": "Placa",
            "empresa": "Cliente / Empresa",
            "mecanico": "Mecánico",
            "tipo_item": "Tipo",
            "descripcion": "Descripción del Trabajo (Editable)",
            "precio_venta": st.column_config.NumberColumn("Precio Venta (Editable)", format="$%d")
        }
    )

    if st.button("💾 Guardar Correcciones en la Base de Datos", type="primary"):
        cambios = df_editado.compare(df_para_editar)
        if not cambios.empty:
            try:
                with engine.begin() as conn_update:
                    for index, row in df_editado.iterrows():
                        desc_orig = df_para_editar.loc[index, 'descripcion']
                        precio_orig = df_para_editar.loc[index, 'precio_venta']
                        
                        if row['descripcion'] != desc_orig or row['precio_venta'] != precio_orig:
                            conn_update.execute(
                                text('''
                                    UPDATE Detalles_Orden 
                                    SET descripcion = :desc, precio_venta = :precio 
                                    WHERE id = :id
                                '''),
                                {"desc": row['descripcion'], "precio": float(row['precio_venta']), "id": int(row['detalle_id'])}
                            )
                
                st.cache_data.clear()
                st.success("✅ ¡Cambios aplicados y sincronizados con éxito!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")
        else:
            st.warning("No se detectaron cambios nuevos para guardar.")
else:
    st.info("No se encontraron trabajos que coincidan con los filtros o criterios de búsqueda.")

st.markdown("---")

# ==========================================
# 2. LIQUIDACIÓN DE NÓMINA (FILTROS Y CÁLCULO)
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
    opciones_mecanicos = ["-- Selecciona un trabajador --"] + list(dict_mecanicos.keys())
    
    st.subheader("📊 Filtros y Parámetros de Liquidación")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        mecanico_sel = st.selectbox("Selecciona el Técnico", options=opciones_mecanicos)
    with col2:
        hoy = datetime.today()
        hace_15_dias = hoy - timedelta(days=15)
        fechas = st.date_input("Rango de fechas para liquidar", [hace_15_dias, hoy])
    with col3:
        porcentaje_pago = st.number_input("Porcentaje a Pagar (%)", min_value=0, max_value=100, value=50, step=5)
        
    if mecanico_sel == "-- Selecciona un trabajador --":
        st.info("👆 Selecciona un trabajador en la casilla de arriba para ver su resumen de liquidación y detalle de pagos.")
    else:
        if len(fechas) == 2:
            fecha_inicio, fecha_fin = fechas
            fecha_fin_extendida = fecha_fin + timedelta(days=1) 
            mecanico_id = dict_mecanicos[mecanico_sel]
            
            query_nomina = text('''
                SELECT h.id as orden_id, h.placa, e.razon_social as empresa, date(h.fecha_ingreso) as fecha, 
                       d.descripcion as descripcion_trabajo, 
                       d.precio_venta as valor_mano_obra
                FROM Detalles_Orden d
                JOIN Hojas_Trabajo h ON d.hoja_id = h.id
                JOIN Empresas_Clientes e ON h.empresa_id = e.id
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
                df_nomina['comision_mecanico'] = (df_nomina['valor_mano_obra'] * (porcentaje_pago / 100)).round(2)
                
                total_mo = df_nomina['valor_mano_obra'].sum()
                total_comision = df_nomina['comision_mecanico'].sum()
                
                st.subheader(f"Resumen de Liquidación: {mecanico_sel}")
                met1, met2, met3 = st.columns(3)
                met1.metric("Trabajos Realizados", len(df_nomina))
                met2.metric("Base (Mano de Obra Ajustada)", formato_cop(total_mo))
                met3.metric(f"Total a Pagar ({porcentaje_pago}%)", formato_cop(total_comision))
                
                st.markdown("#### Detalle de Trabajos para el Recibo de Pago")
                df_mostrar = df_nomina.copy()
                df_mostrar.columns = ['N° Orden', 'Placa', 'Cliente / Empresa', 'Fecha de Ingreso', 'Descripción del Trabajo', 'Cobrado al Cliente ($)', 'Comisión del Técnico ($)']
                
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
