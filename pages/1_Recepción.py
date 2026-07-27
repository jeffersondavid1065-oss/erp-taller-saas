import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion, init_db

st.set_page_config(page_title="Recepcion de Vehiculos", layout="wide")

init_db()

# ==========================================
# ESTILOS CSS ADAPTABLES
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
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.4s ease-out; }
    </style>
""", unsafe_allow_html=True)

if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesion en la pagina principal para acceder a este modulo.")
    st.stop()

user_id = st.session_state.user_id

if 'carrito_items' not in st.session_state:
    st.session_state.carrito_items = []

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

# ==========================================
# OPTIMIZACIÓN: CONSULTAS CACHEADAS (SÚPER RÁPIDAS)
# ==========================================
@st.cache_data(ttl=300) # Guarda clientes y mecánicos en RAM por 5 minutos
def obtener_catalogos(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        empresas_db = conn.execute(text("SELECT id, razon_social FROM Empresas_Clientes WHERE usuario_id = :uid"), {"uid": uid}).fetchall()
        mecanicos_db = conn.execute(text("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid"), {"uid": uid}).fetchall()
    return [tuple(e) for e in empresas_db], [tuple(m) for m in mecanicos_db]

@st.cache_data(ttl=60) # Guarda el inventario en RAM por 1 minuto
def obtener_inventario_activo(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        prods = conn.execute(
            text("SELECT id, nombre_producto, stock_actual, costo_compra, precio_venta FROM Inventario WHERE usuario_id = :uid AND stock_actual > 0 ORDER BY nombre_producto ASC"),
            {"uid": uid}
        ).fetchall()
    return [tuple(p) for p in prods]

st.title("Recepcion y Asignacion de Trabajos")
st.markdown(f"Registrando ordenes para: **{st.session_state.nombre_taller}**")
st.markdown("---")

# Llamadas instantáneas desde la caché
empresas, mecanicos = obtener_catalogos(user_id)

if not empresas or not mecanicos:
    st.warning("Tu taller aun no tiene empresas o mecanicos registrados en la base de datos.")
    st.info("Debes registrar al menos 1 mecanico y 1 cliente para poder asignar trabajos.")
    st.stop()

dict_empresas = {f"{e[1]}": e[0] for e in empresas}
dict_mecanicos = {f"{m[1]}": m[0] for m in mecanicos}
opciones_empresas = ["-- Seleccionar Empresa --"] + list(dict_empresas.keys())
opciones_mecanicos = ["-- Seleccionar Mecanico --"] + list(dict_mecanicos.keys())

# ==========================================
# 1. DATOS DEL VEHICULO
# ==========================================
st.subheader("1. Datos del Vehiculo")
with st.container(border=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        placa = st.text_input("Placa del Vehiculo").upper()
    with col2:
        empresa_sel = st.selectbox("Empresa / Cliente", options=opciones_empresas)
    with col3:
        estado = st.selectbox("Estado Operativo", ["Cotizar", "En revision", "Esperando repuestos", "En reparacion", "Listo para facturar"])

st.markdown("---")

# ==========================================
# 2. AGREGAR TRABAJOS Y REPUESTOS
# ==========================================
st.subheader("2. Agregar Trabajos y Repuestos")
tab1, tab2 = st.tabs(["Mano de Obra", "Repuestos"])

with tab1:
    with st.container(border=True):
        st.markdown("**Agregar Mano de Obra con Retencion Fiscal (%)**")
        col_mo1, col_mo2, col_mo3 = st.columns([2, 1, 1])
        
        with col_mo1:
            desc_mo = st.text_input("Descripcion del trabajo realizado", key="desc_mo")
            mecanico_sel = st.selectbox("Mecanico responsable", options=opciones_mecanicos, key="mec_mo")
        with col_mo2:
            venta_mo = st.number_input("Cobro Bruto al Cliente ($0 si pdte)", min_value=0.0, step=5000.0, key="venta_mo")
        with col_mo3:
            porcentaje_ret = st.number_input("Retencion Fiscal (%)", min_value=0.0, max_value=100.0, step=1.0, key="ret_mo", help="Porcentaje de descuento, ej. 4 o 11.")
        
        valor_descontado = float(venta_mo) * (float(porcentaje_ret) / 100.0)
        neto_mo = max(0.0, float(venta_mo) - valor_descontado)
        
        st.caption(f"Descuento estimado: {formato_cop(valor_descontado)} | Valor Neto para Nomina: **{formato_cop(neto_mo)}**")
            
        st.markdown("")
        if st.button("Agregar Trabajo", use_container_width=True):
            if desc_mo and mecanico_sel != "-- Seleccionar Mecanico --":
                if porcentaje_ret > 0:
                    desc_final = f"{desc_mo} (Ret {porcentaje_ret}% aplicada a la nomina)"
                else:
                    desc_final = desc_mo
                
                st.session_state.carrito_items.append({
                    'Tipo': 'Mano de Obra', 'Descripción': desc_final, 
                    'Mecánico': mecanico_sel, 'Mecánico_ID': dict_mecanicos[mecanico_sel],
                    'Costo': valor_descontado, 
                    'PVP Cliente': float(venta_mo), 
                    'Base_Nomina': neto_mo,
                    'Inventario_ID': None, 'Cantidad_Descontar': 0
                })
                st.rerun()
            else:
                st.error("Completa la descripcion y selecciona un mecanico.")

with tab2:
    with st.container(border=True):
        origen_rep = st.radio("Origen del Repuesto:", ["Comprado afuera (Encargo)", "Tomado del Almacen Propio"], horizontal=True)

        if origen_rep == "Comprado afuera (Encargo)":
            col_rep1, col_rep2, col_rep3 = st.columns([2, 1, 1])
            with col_rep1:
                desc_rep = st.text_input("Nombre del Repuesto", key="desc_rep_ext")
            with col_rep2:
                costo_rep = st.number_input("Costo Compra", min_value=0.0, step=1000.0, key="costo_rep_ext")
                st.caption(f"Costo: {formato_cop(costo_rep)}")
            with col_rep3:
                venta_rep = st.number_input("Precio Venta ($0 si esta pendiente)", min_value=0.0, step=1000.0, key="venta_rep_ext")
                st.caption(f"Venta: {formato_cop(venta_rep)}")
                
            st.markdown("")
            if st.button("Agregar Repuesto Externo", use_container_width=True):
                if desc_rep:
                    st.session_state.carrito_items.append({
                        'Tipo': 'Repuesto', 'Descripción': desc_rep, 
                        'Mecánico': '-', 'Mecánico_ID': None,
                        'Costo': costo_rep, 'PVP Cliente': venta_rep,
                        'Base_Nomina': None,
                        'Inventario_ID': None, 'Cantidad_Descontar': 0
                    })
                    st.rerun()
                else:
                    st.error("Completa la descripcion del repuesto.")

        else:
            prods = obtener_inventario_activo(user_id)

            if prods:
                dict_prods = {f"{p[1]} (Stock: {p[2]} un) - PVP: {formato_cop(p[4])}": p for p in prods}
                prod_sel_key = st.selectbox("Selecciona un producto del almacen:", options=list(dict_prods.keys()))
                prod_data = dict_prods[prod_sel_key]

                col_inv1, col_inv2 = st.columns(2)
                with col_inv1:
                    cant_usar = st.number_input("Cantidad a Usar", min_value=1, max_value=int(prod_data[2]), value=1, step=1)
                with col_inv2:
                    pvp_unitario = float(prod_data[4])
                    st.markdown(f"**Total Cobro:** {formato_cop(pvp_unitario * cant_usar)}")

                st.markdown("")
                if st.button("Agregar del Almacen Propio", use_container_width=True):
                    st.session_state.carrito_items.append({
                        'Tipo': 'Repuesto', 
                        'Descripción': f"{prod_data[1]} (x{cant_usar})",
                        'Mecánico': '-', 'Mecánico_ID': None,
                        'Costo': float(prod_data[3]) * cant_usar,
                        'PVP Cliente': pvp_unitario * cant_usar,
                        'Base_Nomina': None,
                        'Inventario_ID': prod_data[0],
                        'Cantidad_Descontar': cant_usar
                    })
                    st.rerun()
            else:
                st.info("No tienes productos con stock disponible en tu almacen.")

st.markdown("---")

# ==========================================
# 3. RESUMEN DE LA ORDEN (CARRITO)
# ==========================================
st.subheader("3. Resumen de la Orden")
if st.session_state.carrito_items:
    for i, item in enumerate(st.session_state.carrito_items):
        with st.container(border=True):
            col_res1, col_res2, col_res3, col_res4 = st.columns([3, 2, 2, 1])
            with col_res1:
                st.markdown(f"**{item['Tipo']}**: {item['Descripción']}")
            with col_res2:
                if item['Tipo'] == 'Mano de Obra':
                    st.caption(f"Tecnico: {item['Mecánico']}")
                else:
                    st.caption(f"Costo: {formato_cop(item['Costo'])}")
            with col_res3:
                if item['PVP Cliente'] == 0:
                    st.markdown("**Por Cotizar ($0)**")
                else:
                    st.markdown(f"**Cobro al Cliente: {formato_cop(item['PVP Cliente'])}**")
                    if item.get('Base_Nomina') and item['Base_Nomina'] < item['PVP Cliente']:
                        st.caption(f"Base Nomina: {formato_cop(item['Base_Nomina'])}")
            with col_res4:
                if st.button("Quitar", key=f"borrar_{i}", use_container_width=True):
                    st.session_state.carrito_items.pop(i)
                    st.rerun()

    st.markdown("---")
    total_cobro = sum(float(item['PVP Cliente']) for item in st.session_state.carrito_items)
    
    col_tot1, col_tot2 = st.columns([2, 1])
    with col_tot1:
        st.success(f"Total actual a cobrar al cliente: {formato_cop(total_cobro)}")
    with col_tot2:
        if st.button("Guardar Orden Completa", type="primary", use_container_width=True):
            if not placa:
                st.error("Falta ingresar la placa del vehiculo.")
            elif empresa_sel == "-- Seleccionar Empresa --":
                st.error("Por favor, selecciona una Empresa / Cliente valida.")
            else:
                try:
                    empresa_id = dict_empresas[empresa_sel]
                    engine = obtener_conexion()
                    with engine.begin() as conn:
                        is_sqlite = "sqlite" in str(engine.url)
                        
                        if is_sqlite:
                            cursor = conn.execute(
                                text("INSERT INTO Hojas_Trabajo (usuario_id, placa, empresa_id, estado) VALUES (:uid, :placa, :empresa_id, :estado)"), 
                                {"uid": user_id, "placa": placa, "empresa_id": empresa_id, "estado": estado}
                            )
                            hoja_id = cursor.lastrowid
                        else:
                            resultado_hoja = conn.execute(
                                text("INSERT INTO Hojas_Trabajo (usuario_id, placa, empresa_id, estado) VALUES (:uid, :placa, :empresa_id, :estado) RETURNING id"), 
                                {"uid": user_id, "placa": placa, "empresa_id": empresa_id, "estado": estado}
                            )
                            hoja_id = resultado_hoja.scalar()
                        
                        for item in st.session_state.carrito_items:
                            conn.execute(
                                text("INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, costo_compra, precio_venta) VALUES (:hoja_id, :tipo, :desc, :mec_id, :costo, :pvp)"), 
                                {
                                    "hoja_id": hoja_id, "tipo": item['Tipo'], "desc": item['Descripción'], 
                                    "mec_id": item['Mecánico_ID'], "costo": float(item['Costo']), "pvp": float(item['PVP Cliente'])
                                }
                            )
                            if item.get('Inventario_ID'):
                                conn.execute(
                                    text("UPDATE Inventario SET stock_actual = stock_actual - :cant WHERE id = :inv_id"),
                                    {"cant": item['Cantidad_Descontar'], "inv_id": item['Inventario_ID']}
                                )
                    
                    st.session_state.carrito_items = []
                    st.cache_data.clear() # Limpia la RAM para que el inventario se actualice en la próxima carga
                    st.success(f"Orden #{hoja_id} guardada con exito para el vehiculo {placa}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")
else:
    st.info("Aun no se han agregado trabajos ni repuestos a la orden actual.")
