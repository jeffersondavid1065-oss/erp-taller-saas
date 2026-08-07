import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion, mensaje_error_amigable
from queries import obtener_catalogos, invalidar_cache_ordenes

st.set_page_config(page_title="Nómina y Comisiones", layout="wide")

# ==========================================
# ESTILOS CSS: MÁSCARA DERECHA ADAPTABLE Y ANIMACIONES
# ==========================================
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

    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    
    [data-testid="stAppViewBlockContainer"] {
        animation: fade-in-up 0.15s ease-out;
    }
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
    st.warning("🔒 Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

# ==========================================
# FUNCIONES DE CONSULTA OPTIMIZADAS CON CACHÉ
# ==========================================
@st.cache_data(ttl=30)
def obtener_mecanicos_nomina(uid):
    """Solo mecánicos activos: consulta específica de esta página (distinta
    de obtener_catalogos, que trae TODOS los mecánicos sin filtrar estado)."""
    with engine.connect() as conn:
        query = text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid AND estado = 'Activo'")
        return conn.execute(query, {"uid": uid}).fetchall()

st.title("Liquidación de Nómina Dinámica")
st.markdown(f"Auditoría de comisiones y ajustes para: **{nombre_taller}**")
st.markdown("---")

# ==========================================
# 1. MÓDULO DE AUDITORÍA Y FILTROS AVANZADOS
# ==========================================
st.subheader("Auditoría y Corrección de Trabajos")
st.info("Por defecto se muestran los trabajos recientes. Puedes usar los filtros opcionales de abajo para buscar una orden específica por número, placa, fecha, mecánico o empresa.")

with st.expander("Filtros de Búsqueda Avanzada (Opcional)", expanded=False):
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        filtro_nro_orden = st.text_input("N° de Orden (Opcional)")
        filtro_placa = st.text_input("Placa del Vehículo (Opcional)").upper().strip()
    with f_col2:
        filtro_empresa = st.text_input("Nombre de Empresa / Cliente (Opcional)")

        # Reutiliza el catálogo compartido y cacheado (todos los mecánicos,
        # activos o no) en vez de disparar una consulta nueva para el filtro.
        _, mecanicos_todos = obtener_catalogos(user_id)
        lista_nombres_mec = ["-- Todos --"] + [m[1] for m in mecanicos_todos]
        filtro_mecanico_sel = st.selectbox("Mecánico (Opcional)", options=lista_nombres_mec)
    with f_col3:
        activar_filtro_fechas = st.checkbox("Filtrar por Rango de Fechas")
        if activar_filtro_fechas:
            hoy_f = datetime.today()
            hace_30_f = hoy_f - timedelta(days=30)
            rango_auditoria = st.date_input("Rango de Fechas", [hace_30_f, hoy_f])
        else:
            rango_auditoria = None

query_base_sql = [
    '''
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
    WHERE h.usuario_id = :uid AND h.estado != 'Facturado' AND h.factura_estado IS NULL
    '''
]

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

hay_filtros_activos = bool(
    filtro_nro_orden or filtro_placa or filtro_empresa
    or filtro_mecanico_sel != "-- Todos --" or activar_filtro_fechas
)

if not hay_filtros_activos:
    query_final_str = " ".join(query_base_sql) + " ORDER BY h.fecha_ingreso DESC LIMIT 20"
else:
    # Con filtros activos igual se limita a 200 filas: evita traer resultados
    # sin control cuando un filtro (ej. solo placa) sigue devolviendo
    # cientos de registros históricos en talleres con mucho volumen.
    query_final_str = " ".join(query_base_sql) + " ORDER BY h.fecha_ingreso DESC LIMIT 200"

with engine.connect() as conn:
    df_trabajos = pd.read_sql_query(text(query_final_str), con=conn, params=params_auditoria)

if not df_trabajos.empty:
    if hay_filtros_activos and len(df_trabajos) == 200:
        st.caption("⚠️ Mostrando los 200 resultados más recientes que coinciden con el filtro. Afina la búsqueda para ver un rango más preciso.")

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
            "precio_venta": st.column_config.NumberColumn("Precio Venta (Editable)", format="$%,d")
        }
    )

    if st.button("Guardar Correcciones en la Base de Datos", type="primary"):
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
                
                # Estos cambios afectan precio_venta, que impacta métricas del
                # dashboard, el tablero y la lista de pendientes por cotizar.
                invalidar_cache_ordenes()
                st.success("Cambios aplicados y sincronizados con éxito.")
                st.rerun()
            except Exception as e:
                st.error(mensaje_error_amigable(e, "guardar los cambios"))
        else:
            st.warning("No se detectaron cambios nuevos para guardar.")
else:
    st.info("No se encontraron trabajos que coincidan con los filtros o criterios de búsqueda.")

st.markdown("---")

# ==========================================
# 2. LIQUIDACIÓN DE NÓMINA (FILTROS Y CÁLCULO CON RETENCIÓN)
# ==========================================
mecanicos = obtener_mecanicos_nomina(user_id)

if not mecanicos:
    st.info("No hay mecánicos registrados en tu taller.")
else:
    dict_mecanicos = {f"{m[1]}": m[0] for m in mecanicos}
    opciones_mecanicos = ["-- Selecciona un trabajador --"] + list(dict_mecanicos.keys())
    
    st.subheader("Filtros y Parámetros de Liquidación")
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
        st.info("Selecciona un trabajador en la casilla de arriba para ver su resumen de liquidación y detalle de pagos.")
    else:
        if len(fechas) == 2:
            fecha_inicio, fecha_fin = fechas
            fecha_fin_extendida = fecha_fin + timedelta(days=1) 
            mecanico_id = dict_mecanicos[mecanico_sel]
            
            query_nomina = text('''
                SELECT h.id as orden_id, h.placa, e.razon_social as empresa, date(h.fecha_ingreso) as fecha, 
                       d.descripcion as descripcion_trabajo, 
                       d.precio_venta as cobro_cliente,
                       COALESCE(d.costo_compra, 0) as retencion_aplicada
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
                df_nomina['cobro_cliente'] = df_nomina['cobro_cliente'].astype(float)
                df_nomina['retencion_aplicada'] = df_nomina['retencion_aplicada'].astype(float)
                
                df_nomina['base_real_nomina'] = df_nomina['cobro_cliente'] - df_nomina['retencion_aplicada']
                df_nomina['comision_mecanico'] = (df_nomina['base_real_nomina'] * (porcentaje_pago / 100)).round(2)
                
                total_cobrado_cliente = df_nomina['cobro_cliente'].sum()
                total_base_real = df_nomina['base_real_nomina'].sum()
                total_comision = df_nomina['comision_mecanico'].sum()
                
                st.subheader(f"Resumen de Liquidación: {mecanico_sel}")
                met1, met2, met3, met4 = st.columns(4)
                met1.metric("Trabajos Realizados", len(df_nomina))
                met2.metric("Total Cobrado Cliente", formato_cop(total_cobrado_cliente))
                met3.metric("Base Neta (Tras Retención)", formato_cop(total_base_real))
                met4.metric(f"Total a Pagar ({porcentaje_pago}%)", formato_cop(total_comision))
                
                st.markdown("#### Detalle de Trabajos para el Recibo de Pago")
                df_mostrar = df_nomina[['orden_id', 'placa', 'empresa', 'fecha', 'descripcion_trabajo', 'cobro_cliente', 'retencion_aplicada', 'base_real_nomina', 'comision_mecanico']].copy()
                
                df_mostrar.columns = [
                    'N° Orden', 'Placa', 'Cliente / Empresa', 'Fecha de Ingreso', 
                    'Descripción del Trabajo', 'Cobrado al Cliente ($)', 'Retención ($)', 
                    'Base para Nómina ($)', 'Comisión del Técnico ($)'
                ]
                
                st.dataframe(df_mostrar.style.format({
                    'Cobrado al Cliente ($)': lambda x: formato_cop(x),
                    'Retención ($)': lambda x: formato_cop(x),
                    'Base para Nómina ($)': lambda x: formato_cop(x),
                    'Comisión del Técnico ($)': lambda x: formato_cop(x)
                }), use_container_width=True, hide_index=True)
                
                csv = df_mostrar.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"Descargar Soporte de Pago - {mecanico_sel}",
                    data=csv,
                    file_name=f"Liquidacion_{mecanico_sel}.csv",
                    mime="text/csv",
                )
            else:
                st.info(f"No se encontraron trabajos de mano de obra para {mecanico_sel} en este periodo.")
