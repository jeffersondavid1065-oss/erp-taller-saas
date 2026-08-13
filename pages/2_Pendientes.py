import streamlit as st
import html
from sqlalchemy import text
from db import obtener_conexion, mensaje_error_amigable
from queries import obtener_listos_sin_entregar, marcar_entrega

# ==========================================
# ESTILOS CSS CON MÁSCARA DERECHA ADAPTABLE Y ANIMACIÓN
# ==========================================
_mostrar_animacion_pagina = st.session_state.get("_ultima_pagina_animada") != "pendientes"
st.session_state["_ultima_pagina_animada"] = "pendientes"
_anim_pagina_css = (
    '<style>[data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out !important; }</style>'
    if _mostrar_animacion_pagina else ""
)

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
    [data-testid="stExpanderDetails"], [role="tabpanel"] { animation: fade-in-up 0.4s ease-out !important; }
    </style>
""" + _anim_pagina_css, unsafe_allow_html=True)

# --------------------------------------------------------------------------------
# AUTENTICACIÓN: mismo namespace st.session_state.auth definido en app.py
# --------------------------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None}

if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

# Si el token de sesión no está en la URL (ej. tras navegar desde otra
# página), lo vuelve a agregar para que un F5 en esta misma página
# también recupere la sesión, sin depender solo de la cookie.
if "token" not in st.query_params and st.session_state.auth.get("token"):
    st.query_params["token"] = st.session_state.auth["token"]

# Bloqueo de rol: los operarios de Patio solo tienen acceso a Recepción.
if st.session_state.auth.get("rol") == "patio":
    st.warning("🔒 Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

def formato_cop(numero):
    return f"${numero:,.0f}".replace(",", ".")

# ==========================================
# FUNCIONES OPTIMIZADAS CON CACHÉ
# ==========================================
@st.cache_data(ttl=15)
def obtener_ordenes_con_items_pendientes(uid):
    with engine.connect() as conn:
        # h.factura_estado IS NULL: una orden con factura ya creada en Factus
        # (aunque todavía no se haya emitido a la DIAN) no debe poder editarse
        # acá - cambiar el precio dejaría a MyTaller desincronizado de lo que
        # ya quedó facturado.
        query = text('''
            SELECT DISTINCT h.id, h.numero_orden, h.placa, e.razon_social
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            JOIN Detalles_Orden d ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND (d.precio_venta = 0 OR d.precio_venta IS NULL)
              AND h.factura_estado IS NULL
            ORDER BY h.id DESC
        ''')
        return conn.execute(query, {"uid": uid}).fetchall()

@st.cache_data(ttl=15)
def obtener_vehiculos(uid):
    with engine.connect() as conn:
        # Filtra en SQL las órdenes ya facturadas: el Kanban nunca las muestra,
        # así que no tiene sentido traerlas de la base ni mantenerlas en memoria.
        # Esto evita que la consulta crezca indefinidamente con el historial.
        query = text('''
            SELECT h.id, h.numero_orden, h.placa, e.razon_social, h.estado,
                   SUM(CASE WHEN d.precio_venta = 0 OR d.precio_venta IS NULL THEN 1 ELSE 0 END) as items_sin_precio
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            LEFT JOIN Detalles_Orden d ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND h.estado != 'Facturado'
            GROUP BY h.id, h.numero_orden, h.placa, e.razon_social, h.estado
        ''')
        return conn.execute(query, {"uid": uid}).fetchall()

st.title("Tablero de Control Operativo")
st.markdown(f"Patio de vehículos para: **{nombre_taller}**")
st.markdown("---")

# ==========================================
# 1. MÓDULO PARA LIQUIDAR Y COTIZAR TRABAJOS EN $0
# ==========================================
ordenes_sin_precio = obtener_ordenes_con_items_pendientes(user_id)

if ordenes_sin_precio:
    with st.expander(f"Atención: Hay {len(ordenes_sin_precio)} orden(es) con trabajos sin precio asignado", expanded=True):
        dict_pendientes = {f"Orden #{o[1]} - Placa: {o[2]} ({o[3]})": o[0] for o in ordenes_sin_precio}
        dict_numero_por_id = {o[0]: o[1] for o in ordenes_sin_precio}

        orden_sel_key = st.selectbox("Selecciona la orden para asignar o editar precios:", options=list(dict_pendientes.keys()))
        orden_id_sel = dict_pendientes[orden_sel_key]
        numero_orden_sel = dict_numero_por_id[orden_id_sel]
        
        # Consultar ítems de esa orden
        with engine.connect() as conn:
            q_items = text('''
                SELECT d.id, d.tipo_item, d.descripcion, d.costo_compra, d.precio_venta, m.nombre as mecanico
                FROM Detalles_Orden d
                LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
                WHERE d.hoja_id = :hid
            ''')
            items_orden = conn.execute(q_items, {"hid": orden_id_sel}).fetchall()
            
        st.markdown(f"#### Editando Precios para Orden #{numero_orden_sel}")
        
        with st.form(key=f"form_precios_{orden_id_sel}"):
            nuevos_precios = {}
            
            for item in items_orden:
                item_id, tipo, desc, costo, pvp, mec = item
                
                col_i1, col_i2, col_i3, col_i4 = st.columns([3, 2, 2, 2])
                
                with col_i1:
                    st.markdown(f"**{tipo}**: {desc}")
                    if mec and tipo == 'Mano de Obra':
                        st.caption(f"Técnico: {mec}")
                
                with col_i2:
                    if tipo == 'Repuesto':
                        nuevo_costo = st.number_input(f"Costo Compra", value=float(costo or 0), step=1000.0, key=f"costo_{item_id}")
                    else:
                        nuevo_costo = 0.0
                
                with col_i3:
                    nuevo_pvp = st.number_input(f"Precio Venta Cliente", value=float(pvp or 0), step=5000.0, key=f"pvp_{item_id}")
                
                with col_i4:
                    if nuevo_pvp == 0:
                        st.caption("Sin Valor")
                    else:
                        st.caption(f"{formato_cop(nuevo_pvp)}")
                
                nuevos_precios[item_id] = (nuevo_costo, nuevo_pvp)
                st.markdown("---")
            
            btn_guardar_precios = st.form_submit_button("Guardar Precios y Actualizar Orden", type="primary", width='stretch')
            
            if btn_guardar_precios:
                try:
                    with engine.begin() as conn_upd:
                        for item_id, (c_compra, p_venta) in nuevos_precios.items():
                            conn_upd.execute(
                                text('''
                                    UPDATE Detalles_Orden 
                                    SET costo_compra = :costo, precio_venta = :pvp 
                                    WHERE id = :id
                                '''),
                                {"costo": c_compra, "pvp": p_venta, "id": item_id}
                            )
                    # Solo se invalidan las dos consultas afectadas por este cambio
                    # de precios, no todo el cache global (que impactaría a otros
                    # usuarios conectados al mismo servidor).
                    obtener_ordenes_con_items_pendientes.clear()
                    obtener_vehiculos.clear()
                    st.success("Precios actualizados y sincronizados en el sistema.")
                    st.rerun()
                except Exception as e:
                    st.error(mensaje_error_amigable(e, "guardar los precios"))

    st.markdown("---")

# ==========================================
# 2. VEHÍCULOS LISTOS SIN ENTREGAR
# ==========================================
listos_sin_entregar = obtener_listos_sin_entregar(user_id)

if listos_sin_entregar:
    with st.expander(f"{len(listos_sin_entregar)} vehículo(s) listo(s) esperando que el cliente pase a recogerlos", expanded=False):
        for orden_id_le, numero_orden_le, placa_le, empresa_le, estado_le in listos_sin_entregar:
            col_le1, col_le2 = st.columns([3, 1])
            with col_le1:
                st.markdown(f"**Orden #{numero_orden_le}** — Placa {placa_le} — {empresa_le}")
                st.caption(f"Estado: {estado_le}")
            with col_le2:
                if st.button("Marcar Entregado", key=f"entregar_{orden_id_le}", width='stretch'):
                    marcar_entrega(user_id, orden_id_le, True)
                    st.rerun()
            st.divider()

    st.markdown("---")

# ==========================================
# 3. TABLERO KANBAN DE PENDIENTES
# ==========================================
try:
    vehiculos = obtener_vehiculos(user_id)
except Exception as e:
    vehiculos = []
    st.error(mensaje_error_amigable(e, "cargar el tablero"))

def dibujar_estado(titulo, estado_filtro):
    # Cada estado es una ventana desplegable (colapsada por defecto) en vez
    # de una columna siempre visible: con muchas órdenes activas, mostrarlo
    # todo de una vez saturaba la pantalla. Las tarjetas siguen siendo puro
    # texto de solo lectura armado como un solo bloque HTML (más liviano de
    # volver a dibujar en cada clic que un st.container(border=True) por orden).
    ordenes_estado = [v for v in vehiculos if v[4] == estado_filtro]

    with st.expander(f"{titulo} ({len(ordenes_estado)})", expanded=False):
        if not ordenes_estado:
            st.caption("No hay vehículos en este estado por ahora.")
            return

        tarjetas_html = []
        for v in ordenes_estado:
            orden_id, numero_orden, placa, empresa, estado_actual, sin_precio = v
            placa_segura = html.escape(str(placa))
            empresa_segura = html.escape(str(empresa))
            aviso_pendiente = (
                '<div style="font-size:0.9rem; font-weight:600; color:#b45309; margin-top:4px;">Pendiente por Cotizar ($0)</div>'
                if sin_precio and sin_precio > 0 else ""
            )
            tarjetas_html.append(f"""
                <div style="border:1px solid rgba(49,51,63,0.15); border-radius:8px;
                            padding:10px 12px; margin-bottom:8px;">
                    <div style="font-weight:600;">Orden #{numero_orden}</div>
                    <div>Placa: <strong>{placa_segura}</strong></div>
                    <div style="font-size:0.85rem; color:#555;">Empresa: {empresa_segura}</div>
                    {aviso_pendiente}
                </div>
            """)

        st.markdown(''.join(tarjetas_html), unsafe_allow_html=True)

dibujar_estado("Cotizar", "Cotizar")
dibujar_estado("En Revisión", "En revisión")
dibujar_estado("Esperando Repuestos", "Esperando repuestos")
dibujar_estado("En Reparación", "En reparación")
dibujar_estado("Listo para Facturar", "Listo para facturar")

st.markdown("---")
if st.button("Actualizar Tablero", width='stretch'):
    # Igual aquí: solo se limpian las consultas de ESTA página.
    obtener_ordenes_con_items_pendientes.clear()
    obtener_vehiculos.clear()
    st.rerun()
