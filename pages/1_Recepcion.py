import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion

st.set_page_config(page_title="Recepcion de Vehiculos", layout="wide")

# Validacion de Seguridad
if not st.session_state.get('user_logged', False):
    st.warning("Debes iniciar sesion en la pagina principal para acceder a este modulo.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.user_id

if 'carrito_items' not in st.session_state:
    st.session_state.carrito_items = []

def obtener_datos(query, params={}):
    with engine.connect() as conn:
        data = conn.execute(text(query), params).fetchall()
    return data

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("Recepcion y Asignacion de Trabajos")
st.markdown(f"Registrando ordenes para: **{st.session_state.nombre_taller}**")
st.markdown("---")

empresas = obtener_datos("SELECT id, razon_social FROM Empresas_Clientes WHERE usuario_id = :uid", {"uid": user_id})
mecanicos = obtener_datos("SELECT id, nombre FROM Mecanicos WHERE usuario_id = :uid", {"uid": user_id})

if not empresas or not mecanicos:
    st.warning("Tu taller aun no tiene empresas o mecaneicos registrados en la base de datos.")
    st.info("Debes registrar al menos 1 mecanico y 1 cliente para poder asignar trabajos.")
    st.stop()

dict_empresas = {f"{e[1]}": e[0] for e in empresas}
dict_mecanicos = {f"{m[1]}": m[0] for m in mecanicos}

# 1. DATOS DEL VEHICULO
st.subheader("1. Datos del Vehiculo")
with st.container(border=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        placa = st.text_input("Placa del Vehiculo").upper()
    with col2:
        empresa_sel = st.selectbox("Empresa / Cliente", options=list(dict_empresas.keys()))
    with col3:
        estado = st.selectbox("Estado Operativo", ["Cotizar", "En revision", "Esperando repuestos", "En reparacion", "Listo para facturar"])

st.markdown("---")

# 2. AGREGAR TRABAJOS Y REPUESTOS
st.subheader("2. Agregar Trabajos y Repuestos")
tab1, tab2 = st.tabs(["Mano de Obra", "Repuestos"])

with tab1:
    with st.container(border=True):
        col_mo1, col_mo2 = st.columns([2, 1])
        with col_mo1:
            desc_mo = st.text_input("Descripcion del trabajo realizado", key="desc_mo")
            mecanico_sel = st.selectbox("Mecanico responsable", options=list(dict_mecanicos.keys()), key="mec_mo")
        with col_mo2:
            venta_mo = st.number_input("Cobro al Cliente", min_value=0, step=5000, key="venta_mo")
            st.caption(f"Valor a cobrar: {formato_cop(venta_mo)}")
            
            st.markdown("")
            if st.button("Agregar Trabajo", use_container_width=True):
                if desc_mo and venta_mo > 0:
                    st.session_state.carrito_items.append({
                        'Tipo': 'Mano de Obra', 'Descripcion': desc_mo, 
                        'Mecanico': mecanico_sel, 'Mecanico_ID': dict_mecanicos[mecanico_sel],
                        'Costo': 0, 'PVP Cliente': venta_mo
                    })
                    st.rerun()
                else:
                    st.error("Completa la descripcion y el precio.")

with tab2:
    with st.container(border=True):
        col_rep1, col_rep2, col_rep3 = st.columns([2, 1, 1])
        with col_rep1:
            desc_rep = st.text_input("Nombre del Repuesto", key="desc_rep")
        with col_rep2:
            costo_rep = st.number_input("Costo Compra", min_value=0, step=1000, key="costo_rep")
            st.caption(f"Costo: {formato_cop(costo_rep)}")
        with col_rep3:
            venta_rep = st.number_input("Precio Venta", min_value=0, step=1000, key="venta_rep")
            st.caption(f"Venta: {formato_cop(venta_rep)}")
            
        st.markdown("")
        if st.button("Agregar Repuesto", use_container_width=True):
            if desc_rep and venta_rep > 0:
                st.session_state.carrito_items.append({
                    'Tipo': 'Repuesto', 'Descripcion': desc_rep, 
                    'Mecanico': '-', 'Mecanico_ID': None,
                    'Costo': costo_rep, 'PVP Cliente': venta_rep
                })
                st.rerun()
            else:
                st.error("Completa la descripcion y el precio.")

st.markdown("---")

# 3. RESUMEN DE LA ORDEN (CARRITO)
st.subheader("3. Resumen de la Orden")
if st.session_state.carrito_items:
    for i, item in enumerate(st.session_state.carrito_items):
        with st.container(border=True):
            col_res1, col_res2, col_res3, col_res4 = st.columns([3, 2, 2, 1])
            with col_res1:
                st.markdown(f"**{item['Tipo']}**: {item['Descripcion']}")
            with col_res2:
                if item['Tipo'] == 'Mano de Obra':
                    st.caption(f"Tecnico: {item['Mecanico']}")
                else:
                    st.caption(f"Costo: {formato_cop(item['Costo'])}")
            with col_res3:
                st.markdown(f"**Cobro: {formato_cop(item['PVP Cliente'])}**")
            with col_res4:
                if st.button("Quitar", key=f"borrar_{i}", use_container_width=True):
                    st.session_state.carrito_items.pop(i)
                    st.rerun()

    st.markdown("---")
    total_cobro = sum(item['PVP Cliente'] for item in st.session_state.carrito_items)
    
    col_tot1, col_tot2 = st.columns([2, 1])
    with col_tot1:
        st.success(f"Total a cobrar al cliente: {formato_cop(total_cobro)}")
    with col_tot2:
        if st.button("Guardar Orden Completa", type="primary", use_container_width=True):
            if not placa:
                st.error("Falta ingresar la placa del vehiculo.")
            else:
                try:
                    empresa_id = dict_empresas[empresa_sel]
                    
                    with engine.begin() as conn:
                        resultado_hoja = conn.execute(
                            text('''
                                INSERT INTO Hojas_Trabajo (usuario_id, placa, empresa_id, estado) 
                                VALUES (:uid, :placa, :empresa_id, :estado)
                                RETURNING id
                            '''), 
                            {"uid": user_id, "placa": placa, "empresa_id": empresa_id, "estado": estado}
                        )
                        hoja_id = resultado_hoja.scalar()
                        
                        for item in st.session_state.carrito_items:
                            conn.execute(
                                text('''
                                    INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, costo_compra, precio_venta)
                                    VALUES (:hoja_id, :tipo, :desc, :mec_id, :costo, :pvp)
                                '''), 
                                {
                                    "hoja_id": hoja_id, 
                                    "tipo": item['Tipo'], 
                                    "desc": item['Descripcion'], 
                                    "mec_id": item['Mecanico_ID'], 
                                    "costo": float(item['Costo']), 
                                    "pvp": float(item['PVP Cliente'])
                                }
                            )
                    
                    st.session_state.carrito_items = [] 
                    st.success(f"Orden #{hoja_id} guardada con exito para el vehiculo {placa}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")
else:
    st.info("Aun no se han agregado trabajos ni repuestos a la orden actual.")
