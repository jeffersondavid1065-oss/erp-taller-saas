import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion, init_db
from queries import obtener_catalogos, obtener_inventario_activo, invalidar_cache_ordenes, invalidar_cache_inventario

st.set_page_config(page_title="Recepcion de Vehiculos", layout="wide")

init_db()

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
    [data-testid="stToolbar"] { display: none !important; }
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }
    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.4s ease-out; }
    </style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------------
# AUTENTICACIÓN
# --------------------------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesion en la pagina principal para acceder a este modulo.")
    st.stop()

user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

if 'carrito_items' not in st.session_state:
    st.session_state.carrito_items = []

# Limpiar buscador de código de barras
if "limpiar_cod_rep" not in st.session_state:
    st.session_state.limpiar_cod_rep = False

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

st.title("Recepcion y Asignacion de Trabajos")
st.markdown(f"Registrando ordenes para: **{nombre_taller}**")
st.markdown("---")

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
        estado = st.selectbox("Estado Operativo", [
            "Cotizar", "En revision", "Esperando repuestos",
            "En reparacion", "Listo para facturar"
        ])

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
            porcentaje_ret = st.number_input("Retencion Fiscal (%)", min_value=0.0, max_value=100.0, step=1.0, key="ret_mo")

        valor_descontado = float(venta_mo) * (float(porcentaje_ret) / 100.0)
        neto_mo = max(0.0, float(venta_mo) - valor_descontado)
        st.caption(f"Descuento estimado: {formato_cop(valor_descontado)} | Valor Neto para Nomina: **{formato_cop(neto_mo)}**")

        st.markdown("")
        if st.button("Agregar Trabajo", use_container_width=True):
            if desc_mo and mecanico_sel != "-- Seleccionar Mecanico --":
                desc_final = f"{desc_mo} (Ret {porcentaje_ret}% aplicada a la nomina)" if porcentaje_ret > 0 else desc_mo
                st.session_state.carrito_items.append({
                    'Tipo': 'Mano de Obra', 'Descripción': desc_final,
                    'Mecánico': mecanico_sel, 'Mecánico_ID': dict_mecanicos[mecanico_sel],
                    'Costo': valor_descontado, 'PVP Cliente': float(venta_mo),
                    'Base_Nomina': neto_mo,
                    'Inventario_ID': None, 'Cantidad_Descontar': 0
                })
                st.rerun()
            else:
                st.error("Completa la descripcion y selecciona un mecanico.")

with tab2:
    with st.container(border=True):
        origen_rep = st.radio(
            "Origen del Repuesto:",
            ["Comprado afuera (Encargo)", "Tomado del Almacen Propio"],
            horizontal=True
        )

        if origen_rep == "Comprado afuera (Encargo)":
            col_rep1, col_rep2, col_rep3 = st.columns([2, 1, 1])
            with col_rep1:
                desc_rep = st.text_input("Nombre del Repuesto", key="desc_rep_ext")
            with col_rep2:
                costo_rep = st.number_input("Costo Compra", min_value=0.0, step=1000.0, key="costo_rep_ext")
                st.caption(f"Costo: {formato_cop(costo_rep)}")
            with col_rep3:
                venta_rep = st.number_input("Precio Venta ($0 si pdte)", min_value=0.0, step=1000.0, key="venta_rep_ext")
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
            # ==========================================
            # BÚSQUEDA POR CÓDIGO DE BARRAS O NOMBRE
            # ==========================================
            st.markdown("**🔍 Buscar repuesto**")
            st.caption("Escanea el código de barras del repuesto o escribe el nombre.")

            # Limpiar campo si viene de un escaneo exitoso
            if st.session_state.limpiar_cod_rep:
                st.session_state.limpiar_cod_rep = False
                st.session_state.cod_rep_buscador = ""

            busqueda_rep = st.text_input(
                "Código de barras o nombre",
                placeholder="Escanea con el lector o escribe el nombre...",
                key="cod_rep_buscador",
                label_visibility="collapsed"
            )

            prods = obtener_inventario_activo(user_id)

            if busqueda_rep and prods:
                busqueda_clean = busqueda_rep.strip()

                # Buscar por código de referencia exacto (lector físico)
                prod_por_codigo = next(
                    (p for p in prods if str(p[5] or "").strip() == busqueda_clean),
                    None
                )

                if prod_por_codigo:
                    # Encontrado por código — mostrar y agregar directo
                    p = prod_por_codigo
                    with st.container(border=True):
                        col_c1, col_c2, col_c3 = st.columns([3, 1, 1])
                        with col_c1:
                            st.markdown(f"**{p[1]}**")
                            st.caption(f"Código: {p[5]} | Stock: {p[2]} uds.")
                        with col_c2:
                            cant_usar = st.number_input(
                                "Cantidad", min_value=1,
                                max_value=int(p[2]), value=1, step=1,
                                key="cant_cod"
                            )
                            st.caption(f"Total: {formato_cop(float(p[4]) * cant_usar)}")
                        with col_c3:
                            st.write("")
                            st.write("")
                            if st.button("✅ Agregar", type="primary", use_container_width=True, key="btn_agregar_cod"):
                                st.session_state.carrito_items.append({
                                    'Tipo': 'Repuesto',
                                    'Descripción': f"{p[1]} (x{cant_usar})",
                                    'Mecánico': '-', 'Mecánico_ID': None,
                                    'Costo': float(p[3]) * cant_usar,
                                    'PVP Cliente': float(p[4]) * cant_usar,
                                    'Base_Nomina': None,
                                    'Inventario_ID': p[0],
                                    'Cantidad_Descontar': cant_usar
                                })
                                st.session_state.limpiar_cod_rep = True
                                st.rerun()
                else:
                    # Buscar por nombre
                    prods_filtrados = [
                        p for p in prods
                        if busqueda_clean.lower() in p[1].lower()
                    ]

                    if prods_filtrados:
                        st.markdown(f"**{len(prods_filtrados)} resultado(s):**")
                        for p in prods_filtrados:
                            with st.container(border=True):
                                col_r1, col_r2, col_r3 = st.columns([3, 1, 1])
                                with col_r1:
                                    st.write(f"**{p[1]}**")
                                    if p[5]:
                                        st.caption(f"Cód: {p[5]}")
                                    st.caption(f"Stock: {p[2]} uds. | PVP: {formato_cop(p[4])}")
                                with col_r2:
                                    cant = st.number_input(
                                        "Cant.", min_value=1,
                                        max_value=int(p[2]), value=1, step=1,
                                        key=f"cant_{p[0]}"
                                    )
                                with col_r3:
                                    st.write("")
                                    if st.button("Agregar", key=f"add_{p[0]}", use_container_width=True):
                                        st.session_state.carrito_items.append({
                                            'Tipo': 'Repuesto',
                                            'Descripción': f"{p[1]} (x{cant})",
                                            'Mecánico': '-', 'Mecánico_ID': None,
                                            'Costo': float(p[3]) * cant,
                                            'PVP Cliente': float(p[4]) * cant,
                                            'Base_Nomina': None,
                                            'Inventario_ID': p[0],
                                            'Cantidad_Descontar': cant
                                        })
                                        st.rerun()
                    else:
                        st.warning(f"No se encontró '{busqueda_clean}' en el almacén.")

            elif not busqueda_rep and prods:
                # Sin búsqueda — mostrar selector dropdown clásico
                st.markdown("**O selecciona del listado:**")
                dict_prods = {
                    f"{p[1]} (Stock: {p[2]} un) - PVP: {formato_cop(p[4])}": p
                    for p in prods
                }
                prod_sel_key = st.selectbox(
                    "Selecciona un producto del almacen:",
                    options=list(dict_prods.keys())
                )
                prod_data = dict_prods[prod_sel_key]

                col_inv1, col_inv2 = st.columns(2)
                with col_inv1:
                    cant_usar = st.number_input(
                        "Cantidad a Usar", min_value=1,
                        max_value=int(prod_data[2]), value=1, step=1
                    )
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
            elif not prods:
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
                                    "hoja_id": hoja_id, "tipo": item['Tipo'],
                                    "desc": item['Descripción'], "mec_id": item['Mecánico_ID'],
                                    "costo": float(item['Costo']), "pvp": float(item['PVP Cliente'])
                                }
                            )
                            if item.get('Inventario_ID'):
                                conn.execute(
                                    text("UPDATE Inventario SET stock_actual = stock_actual - :cant WHERE id = :inv_id AND stock_actual >= :cant"),
                                    {"cant": item['Cantidad_Descontar'], "inv_id": item['Inventario_ID']}
                                )

                    hay_items_de_almacen = any(item.get('Inventario_ID') for item in st.session_state.carrito_items)
                    st.session_state.carrito_items = []
                    invalidar_cache_ordenes()
                    if hay_items_de_almacen:
                        invalidar_cache_inventario()

                    st.success(f"Orden #{hoja_id} guardada con exito para el vehiculo {placa}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")
else:
    st.info("Aun no se han agregado trabajos ni repuestos a la orden actual.")
