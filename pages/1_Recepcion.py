import streamlit as st
import sqlite3
import pandas as pd
import os

st.set_page_config(page_title="Recepción de Vehículos", page_icon="🚘", layout="wide")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")

# Validación de Seguridad: Si no ha iniciado sesión, lo devuelve al Login
if not st.session_state.get('user_logged', False):
    st.warning("⚠️ Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

user_id = st.session_state.user_id

if 'carrito_items' not in st.session_state:
    st.session_state.carrito_items = []

def obtener_datos(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    data = cursor.fetchall()
    conn.close()
    return data

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

st.title("🚘 Recepción y Asignación de Trabajos")
st.markdown(f"Registrando órdenes para: **{st.session_state.nombre_taller}**")
st.markdown("---")

# Filtramos los datos estrictamente por el usuario (taller) actual
empresas = obtener_datos("SELECT id, razon_social FROM Empresas_Clientes WHERE usuario_id = ?", (user_id,))
mecanicos = obtener_datos("SELECT id, nombre FROM Mecanicos WHERE usuario_id = ?", (user_id,))

if not empresas or not mecanicos:
    st.warning("⚠️ Tu taller aún no tiene empresas o mecánicos registrados. Ve a Directorio o Clientes para agregarlos primero.")
    st.stop()

dict_empresas = {f"{e[1]}": e[0] for e in empresas}
dict_mecanicos = {f"{m[1]}": m[0] for m in mecanicos}

st.subheader("1. Datos del Vehículo")
col1, col2, col3 = st.columns(3)
with col1:
    placa = st.text_input("Placa del Vehículo").upper()
with col2:
    empresa_sel = st.selectbox("Empresa / Cliente", options=list(dict_empresas.keys()))
with col3:
    estado = st.selectbox("Estado Operativo", ["Cotizar", "En revisión", "Esperando repuestos", "En reparación", "Listo para facturar"])

st.markdown("---")
st.subheader("2. Agregar Trabajos y Repuestos")
tab1, tab2 = st.tabs(["🔧 Agregar Mano de Obra", "📦 Agregar Repuesto"])

with tab1:
    col_mo1, col_mo2 = st.columns([2, 1])
    with col_mo1:
        desc_mo = st.text_input("Descripción del trabajo realizado", key="desc_mo")
        mecanico_sel = st.selectbox("Mecánico que lo realiza", options=list(dict_mecanicos.keys()), key="mec_mo")
    with col_mo2:
        venta_mo = st.number_input("Cobro al Cliente", min_value=0, step=5000, key="venta_mo")
        st.info(f"👀 Verificador: **{formato_cop(venta_mo)}**")
        
        if st.button("➕ Agregar Trabajo"):
            if desc_mo and venta_mo > 0:
                st.session_state.carrito_items.append({
                    'Tipo': 'Mano de Obra', 'Descripción': desc_mo, 
                    'Mecánico': mecanico_sel, 'Mecánico_ID': dict_mecanicos[mecanico_sel],
                    'Costo': 0, 'PVP Cliente': venta_mo
                })
                st.rerun()
            else:
                st.error("Llenar descripción y precio.")

with tab2:
    col_rep1, col_rep2, col_rep3 = st.columns([2, 1, 1])
    with col_rep1:
        desc_rep = st.text_input("Nombre del Repuesto", key="desc_rep")
    with col_rep2:
        costo_rep = st.number_input("Costo Compra", min_value=0, step=1000, key="costo_rep")
        st.info(f"👀 Costo: **{formato_cop(costo_rep)}**")
    with col_rep3:
        venta_rep = st.number_input("Precio Venta", min_value=0, step=1000, key="venta_rep")
        st.info(f"👀 Venta: **{formato_cop(venta_rep)}**")
        if st.button("➕ Agregar Repuesto"):
            if desc_rep and venta_rep > 0:
                st.session_state.carrito_items.append({
                    'Tipo': 'Repuesto', 'Descripción': desc_rep, 
                    'Mecánico': '-', 'Mecánico_ID': None,
                    'Costo': costo_rep, 'PVP Cliente': venta_rep
                })
                st.rerun()
            else:
                st.error("Llenar descripción y precio.")

st.markdown("---")
st.subheader("3. Resumen de la Orden (Carrito)")
if st.session_state.carrito_items:
    st.markdown("Revisa los ítems antes de guardar.")
    for i, item in enumerate(st.session_state.carrito_items):
        with st.container(border=True):
            col_res1, col_res2, col_res3, col_res4 = st.columns([3, 2, 2, 1])
            with col_res1:
                st.markdown(f"**{item['Tipo']}**: {item['Descripción']}")
            with col_res2:
                if item['Tipo'] == 'Mano de Obra':
                    st.caption(f"👨‍🔧 Técnico: {item['Mecánico']}")
                else:
                    st.caption(f"📦 Costo Taller: {formato_cop(item['Costo'])}")
            with col_res3:
                st.markdown(f"**Cobro: {formato_cop(item['PVP Cliente'])}**")
            with col_res4:
                if st.button("🗑️ Eliminar", key=f"borrar_{i}"):
                    st.session_state.carrito_items.pop(i)
                    st.rerun()

    st.markdown("---")
    total_cobro = sum(item['PVP Cliente'] for item in st.session_state.carrito_items)
    st.success(f"**Total a cobrar al cliente por esta orden:** {formato_cop(total_cobro)}")
    
    if st.button("💾 Guardar Orden de Ingreso Completa", type="primary"):
        if not placa:
            st.error("Falta escribir la Placa.")
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            try:
                empresa_id = dict_empresas[empresa_sel]
                # 🌟 GUARDAMOS AMARRADO AL USUARIO_ID DEL TALLER ACTUAL
                c.execute('''
                    INSERT INTO Hojas_Trabajo (usuario_id, placa, empresa_id, estado) 
                    VALUES (?, ?, ?, ?)
                ''', (user_id, placa, empresa_id, estado))
                hoja_id = c.lastrowid
                
                for item in st.session_state.carrito_items:
                    c.execute('''
                        INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, costo_compra, precio_venta)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (hoja_id, item['Tipo'], item['Descripción'], item['Mecánico_ID'], item['Costo'], item['PVP Cliente']))
                
                conn.commit()
                st.session_state.carrito_items = [] 
                st.success(f"✅ ¡Orden #{hoja_id} guardada exitosamente para el vehículo {placa}!")
            except Exception as e:
                st.error(f"Error al guardar: {e}")
            finally:
                conn.close()
else:
    st.info("Aún no has agregado trabajos ni repuestos.")