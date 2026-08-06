import streamlit as st
import html
from sqlalchemy import text
from db import obtener_conexion, mensaje_error_amigable

st.set_page_config(page_title="Tablero de Control", layout="wide")

# ==========================================
# ESTILOS CSS CON MÁSCARA DERECHA ADAPTABLE Y ANIMACIÓN
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
        animation: fade-in-up 0.6s ease-out;
    }

    .kanban-column {
        padding: 16px;
        border-radius: 12px;
        margin-bottom: 10px;
        border: 1px solid rgba(0, 0, 0, 0.04);
    }
    .bg-cotizar { background-color: #f0f4f8; }
    .bg-revision { background-color: #fcf8e8; }
    .bg-repuestos { background-color: #fbf1ed; }
    .bg-reparacion { background-color: #f0ebf8; }
    .bg-facturar { background-color: #edf7ed; }
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
    return f"${numero:,.0f}".replace(",", ".")

# ==========================================
# FUNCIONES OPTIMIZADAS CON CACHÉ
# ==========================================
@st.cache_data(ttl=15)
def obtener_ordenes_con_items_pendientes(uid):
    with engine.connect() as conn:
        # h.factura_estado IS NULL: una orden con factura ya creada en Alegra
        # (aunque todavía no se haya emitido a la DIAN) no debe poder editarse
        # acá - cambiar el precio dejaría a MyTaller desincronizado de lo que
        # ya quedó facturado.
        query = text('''
            SELECT DISTINCT h.id, h.placa, e.razon_social
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
            SELECT h.id, h.placa, e.razon_social, h.estado,
                   SUM(CASE WHEN d.precio_venta = 0 OR d.precio_venta IS NULL THEN 1 ELSE 0 END) as items_sin_precio
            FROM Hojas_Trabajo h
            JOIN Empresas_Clientes e ON h.empresa_id = e.id
            LEFT JOIN Detalles_Orden d ON d.hoja_id = h.id
            WHERE h.usuario_id = :uid AND h.estado != 'Facturado'
            GROUP BY h.id, h.placa, e.razon_social, h.estado
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
        dict_pendientes = {f"Orden #{o[0]} - Placa: {o[1]} ({o[2]})": o[0] for o in ordenes_sin_precio}
        
        orden_sel_key = st.selectbox("Selecciona la orden para asignar o editar precios:", options=list(dict_pendientes.keys()))
        orden_id_sel = dict_pendientes[orden_sel_key]
        
        # Consultar ítems de esa orden
        with engine.connect() as conn:
            q_items = text('''
                SELECT d.id, d.tipo_item, d.descripcion, d.costo_compra, d.precio_venta, m.nombre as mecanico
                FROM Detalles_Orden d
                LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
                WHERE d.hoja_id = :hid
            ''')
            items_orden = conn.execute(q_items, {"hid": orden_id_sel}).fetchall()
            
        st.markdown(f"#### Editando Precios para Orden #{orden_id_sel}")
        
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
            
            btn_guardar_precios = st.form_submit_button("Guardar Precios y Actualizar Orden", type="primary", use_container_width=True)
            
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
# 2. TABLERO KANBAN DE PENDIENTES
# ==========================================
try:
    vehiculos = obtener_vehiculos(user_id)
except Exception as e:
    vehiculos = []
    st.error(mensaje_error_amigable(e, "cargar el tablero"))

col1, col2, col3, col4, col5 = st.columns(5)

def dibujar_columna(columna, titulo, estado_filtro, clase_css):
    # Las tarjetas son puro texto de solo lectura (sin botones ni campos
    # adentro), así que se arma todo el HTML de la columna de una sola vez
    # en vez de un st.container(border=True) nativo por tarjeta: mismo look,
    # una sola llamada a Streamlit por columna en lugar de una por orden -
    # mucho menos trabajo para volver a dibujar en cada clic.
    tarjetas_html = []
    for v in vehiculos:
        orden_id, placa, empresa, estado_actual, sin_precio = v
        if estado_actual == estado_filtro:
            placa_segura = html.escape(str(placa))
            empresa_segura = html.escape(str(empresa))
            aviso_pendiente = (
                '<div style="font-size:0.9rem; font-weight:600; color:#b45309; margin-top:4px;">Pendiente por Cotizar ($0)</div>'
                if sin_precio and sin_precio > 0 else ""
            )
            tarjetas_html.append(f"""
                <div style="border:1px solid rgba(49,51,63,0.15); border-radius:8px;
                            padding:10px 12px; margin-bottom:8px; background:rgba(255,255,255,0.6);">
                    <div style="font-weight:600;">Orden #{orden_id}</div>
                    <div>Placa: <strong>{placa_segura}</strong></div>
                    <div style="font-size:0.85rem; color:#555;">Empresa: {empresa_segura}</div>
                    {aviso_pendiente}
                </div>
            """)

    if not tarjetas_html:
        tarjetas_html.append(
            '<div style="color:#666; font-size:0.95rem; padding:6px 0;">'
            'No hay vehículos en este estado por ahora.</div>'
        )

    with columna:
        st.markdown(f"""
            <div class="kanban-column {clase_css}">
                <h4 style="margin-top: 0; font-weight: 600; color: #31333F; font-size: 1.1rem;">{titulo}</h4>
                <hr style="margin: 8px 0; border: none; border-top: 1px solid rgba(0,0,0,0.08);">
                {''.join(tarjetas_html)}
            </div>
        """, unsafe_allow_html=True)

dibujar_columna(col1, "Cotizar", "Cotizar", "bg-cotizar")
dibujar_columna(col2, "En Revisión", "En revisión", "bg-revision")
dibujar_columna(col3, "Esperando Repuestos", "Esperando repuestos", "bg-repuestos")
dibujar_columna(col4, "En Reparación", "En reparación", "bg-reparacion")
dibujar_columna(col5, "Listo para Facturar", "Listo para facturar", "bg-facturar")

st.markdown("---")
if st.button("Actualizar Tablero", use_container_width=True):
    # Igual aquí: solo se limpian las consultas de ESTA página.
    obtener_ordenes_con_items_pendientes.clear()
    obtener_vehiculos.clear()
    st.rerun()
