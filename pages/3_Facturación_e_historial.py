import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion, init_db
from queries import (
    obtener_catalogos, obtener_config_taller, invalidar_cache_ordenes, invalidar_cache_inventario,
    tiene_fe_habilitada, obtener_credenciales_alegra,
)
from io import BytesIO
from pdf_utils import generar_pdf_orden_profesional, calcular_totales_orden, IVA_OPCIONES
import alegra_utils

st.set_page_config(page_title="Expediente", layout="wide")

init_db()

# ==========================================
# ESTILOS CSS: MÁSCARA DERECHA ADAPTABLE, ANIMACIONES Y DISEÑO
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
    
    div[data-testid="stVerticalBlock"] > div {
        animation: fade-in-up 0.5s ease-out;
    }

    .expediente-card {
        background-color: #f8fafc;
        padding: 16px;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        margin-bottom: 10px;
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
    return f"${numero:,.0f}".replace(",", ".")

# --------------------------------------------------------------------------------
# CONFIGURACIÓN DE IVA DEL TALLER (config global, definida en Configuración)
# --------------------------------------------------------------------------------
# Config del taller cacheada (antes era una consulta cruda sin caché
# repetida en cada rerun de esta página)
_config_taller = obtener_config_taller(user_id)

IVA_ACTIVO = bool(_config_taller[4]) if _config_taller and _config_taller[4] is not None else False
IVA_INCLUIDO = bool(_config_taller[5]) if _config_taller and _config_taller[5] is not None else False
IVA_TIPO_DEFAULT_MO = _config_taller[6] if _config_taller and _config_taller[6] in IVA_OPCIONES else "Excluido"
IVA_TIPO_DEFAULT_REP = _config_taller[7] if _config_taller and _config_taller[7] in IVA_OPCIONES else "Excluido"

st.title("Expediente de Orden y Facturación")
st.markdown(f"Gestión de órdenes para: **{nombre_taller}**")
if IVA_ACTIVO:
    modo_iva_txt = "incluido en el precio" if IVA_INCLUIDO else "se suma aparte al precio"
    st.caption(
        f"🧾 IVA activo ({modo_iva_txt}) | Default Mano de Obra: **{IVA_TIPO_DEFAULT_MO}** · "
        f"Default Repuestos: **{IVA_TIPO_DEFAULT_REP}**. Configurable en 'Configuración del Taller'."
    )
else:
    st.caption("🧾 Este taller no cobra IVA (todos los ítems se facturan como 'Excluido').")
st.markdown("---")

# Catálogos cacheados y compartidos con el resto de la app (no se vuelven
# a consultar en cada rerun, y quedan sincronizados con Recepción/Tablero).
empresas, mecanicos = obtener_catalogos(user_id)
dict_mecanicos = {f"{m[1]}": m[0] for m in mecanicos}
dict_empresas_filtro = {e[1]: e[0] for e in empresas}
opciones_empresas_filtro = ["-- Todas las empresas --"] + list(dict_empresas_filtro.keys())

st.subheader("Historial y Filtros de Órdenes")
st.info("Utiliza los filtros de búsqueda avanzada para localizar órdenes por estado, placa o empresa de forma inmediata.")

# ==========================================
# PANEL DE FILTROS AVANZADOS OPCIONALES
# ==========================================
with st.expander("Filtros de Búsqueda Avanzada", expanded=True):
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        hoy = datetime.today()
        hace_30_dias = hoy - timedelta(days=30)
        fechas_filtro = st.date_input("Rango de fechas", [hace_30_dias, hoy])
    with col_f2:
        estados_opciones = ["-- Todos los estados --", "Cotizar", "En revisión", "Esperando repuestos", "En reparación", "Listo para facturar", "Facturado"]
        filtro_estado_sel = st.selectbox("Estado del Trabajo", options=estados_opciones)
    with col_f3:
        filtro_placa_exp = st.text_input("Placa del Vehículo (Opcional)").upper().strip()
        filtro_empresa_sel = st.selectbox("Empresa / Cliente (Opcional)", options=opciones_empresas_filtro)

if len(fechas_filtro) == 2:
    fecha_inicio, fecha_fin = fechas_filtro
    fecha_fin_extendida = fecha_fin + timedelta(days=1) 

    sql_count_parts = [
        "SELECT COUNT(*) FROM Hojas_Trabajo h JOIN Empresas_Clientes e ON h.empresa_id = e.id WHERE h.usuario_id = :uid AND h.fecha_ingreso >= :f_ini AND h.fecha_ingreso < :f_fin"
    ]
    
    sql_list_select = '''
        SELECT h.id as "N° Orden", date(h.fecha_ingreso) as "Fecha", 
               h.placa as "Placa", e.razon_social as "Empresa", 
               COALESCE(SUM(d.precio_venta), 0) as "Total",
               h.estado as "Estado"
        FROM Hojas_Trabajo h
        JOIN Empresas_Clientes e ON h.empresa_id = e.id
        LEFT JOIN Detalles_Orden d ON h.id = d.hoja_id
        WHERE h.usuario_id = :uid AND h.fecha_ingreso >= :f_ini AND h.fecha_ingreso < :f_fin
    '''
    
    sql_conditions = []

    params_exp = {
        "uid": user_id, 
        "f_ini": fecha_inicio.strftime('%Y-%m-%d'), 
        "f_fin": fecha_fin_extendida.strftime('%Y-%m-%d')
    }

    if filtro_estado_sel != "-- Todos los estados --":
        sql_count_parts.append("AND h.estado = :est")
        sql_conditions.append("AND h.estado = :est")
        params_exp["est"] = filtro_estado_sel

    if filtro_placa_exp:
        sql_count_parts.append("AND h.placa LIKE :placa")
        sql_conditions.append("AND h.placa LIKE :placa")
        params_exp["placa"] = f"%{filtro_placa_exp}%"

    if filtro_empresa_sel != "-- Todas las empresas --":
        sql_count_parts.append("AND e.razon_social = :empresa_nombre")
        sql_conditions.append("AND e.razon_social = :empresa_nombre")
        params_exp["empresa_nombre"] = filtro_empresa_sel

    with engine.connect() as conn:
        total_registros = conn.execute(text(" ".join(sql_count_parts)), params_exp).scalar()

    if total_registros > 0:
        REGISTROS_POR_PAGINA = 20
        total_paginas = math.ceil(total_registros / REGISTROS_POR_PAGINA)
        
        col_pag1, col_pag2 = st.columns([2, 2])
        with col_pag2:
            if total_paginas > 1:
                pagina_actual = st.number_input("Ir a la Página", min_value=1, max_value=total_paginas, value=1)
            else:
                pagina_actual = 1
                st.text("Página 1 de 1")
        
        offset = (pagina_actual - 1) * REGISTROS_POR_PAGINA
        
        sql_final_list = sql_list_select + " " + " ".join(sql_conditions) + " GROUP BY h.id, h.fecha_ingreso, h.placa, e.razon_social, h.estado ORDER BY h.id DESC LIMIT :limit OFFSET :offset"
        params_exp["limit"] = REGISTROS_POR_PAGINA
        params_exp["offset"] = offset

        with engine.connect() as conn:
            df_lista = pd.read_sql_query(text(sql_final_list), con=conn, params=params_exp)

        st.dataframe(
            df_lista.style.format({'Total': lambda x: formato_cop(x)}),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("No se encontraron órdenes que coincidan con los filtros seleccionados.")
else:
    st.warning("Por favor selecciona un rango de fechas válido.")

st.markdown("---")

st.subheader("Abrir Expediente Específico")
st.markdown("Ingresa el número de orden para consultar detalles, auditar o modificar registros.")

orden_busqueda = st.text_input("Número de Orden")

if orden_busqueda:
    if orden_busqueda.isdigit(): 
        orden_id = int(orden_busqueda)
        
        with engine.connect() as conn:
            query_vehiculo = text('''
                SELECT h.id, h.placa, h.estado, h.fecha_ingreso, e.razon_social, e.nit,
                       h.factura_estado, h.nota_credito_alegra_id, h.factura_prefijo, h.factura_numero
                FROM Hojas_Trabajo h
                JOIN Empresas_Clientes e ON h.empresa_id = e.id
                WHERE h.id = :oid AND h.usuario_id = :uid
            ''')
            vehiculo = conn.execute(query_vehiculo, {"oid": orden_id, "uid": user_id}).fetchone()

        if not vehiculo:
            st.warning(f"No se encontró ninguna orden con el número #{orden_id} en tu taller.")
        else:
            (hoja_id, placa, estado_actual, fecha, cliente, nit, factura_estado_actual,
             nota_credito_actual, factura_prefijo_actual, factura_numero_actual) = vehiculo
            numero_factura_actual = f"{factura_prefijo_actual or ''}{factura_numero_actual or ''}"
            
            st.markdown(f"### Expediente de Orden #{hoja_id} | Placa: {placa}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Cliente", cliente)
            col2.metric("NIT", nit)
            col3.metric("Estado Actual", estado_actual)
            
            with engine.connect() as conn:
                df_trabajos = pd.read_sql_query(
                    text('''
                        SELECT d.id, d.tipo_item, d.descripcion, m.nombre as mecanico, 
                               d.costo_compra, d.precio_venta, d.iva_tipo
                        FROM Detalles_Orden d
                        LEFT JOIN Mecanicos m ON d.mecanico_id = m.id
                        WHERE d.hoja_id = :hid
                    '''), 
                    con=conn, 
                    params={"hid": hoja_id}
                )

            # Cálculo de totales usando el tipo de impuesto de cada ítem (o el
            # default de su categoría si el ítem no tiene uno asignado).
            subtotal_orden, iva_valor_orden, gran_total, desglose_iva_orden = calcular_totales_orden(
                df_trabajos, iva_activo=IVA_ACTIVO, iva_incluido=IVA_INCLUIDO,
                iva_tipo_default_mano_obra=IVA_TIPO_DEFAULT_MO, iva_tipo_default_repuestos=IVA_TIPO_DEFAULT_REP
            )

            # La pestaña "Anular" solo tiene sentido si la orden ya tiene una
            # factura electrónica emitida y todavía no se le hizo nota crédito -
            # por eso los tabs se arman dinámicamente en vez de con una lista fija.
            mostrar_tab_anular = (factura_estado_actual == "emitida") and not nota_credito_actual

            nombres_tabs = ["Detalles y Copia de Ítems", "Facturar"]
            if mostrar_tab_anular:
                nombres_tabs.append("Anular")
            nombres_tabs.append("Edición y Gestión")

            tabs_creados = st.tabs(nombres_tabs)
            tab_factura = tabs_creados[0]
            tab_facturar_dian = tabs_creados[1]
            if mostrar_tab_anular:
                tab_anular = tabs_creados[2]
                tab_editar = tabs_creados[3]
            else:
                tab_editar = tabs_creados[2]
            
            with tab_factura:
                if not df_trabajos.empty:
                    df_mostrar = df_trabajos[['tipo_item', 'descripcion', 'mecanico', 'precio_venta', 'iva_tipo']].copy()
                    df_mostrar['iva_tipo'] = df_mostrar['iva_tipo'].fillna('(default de categoría)')
                    df_mostrar.columns = ['Tipo', 'Descripción', 'Técnico', 'Cobro al Cliente', 'Impuesto (IVA)']
                    st.dataframe(
                        df_mostrar.style.format({'Cobro al Cliente': lambda x: formato_cop(x)}),
                        use_container_width=True, hide_index=True
                    )

                    if IVA_ACTIVO:
                        n_cols = 2 + max(len(desglose_iva_orden), 1)
                        cols_tot = st.columns(n_cols)
                        cols_tot[0].metric("Subtotal", formato_cop(subtotal_orden))
                        if desglose_iva_orden:
                            for idx_iva, (etiqueta, monto) in enumerate(desglose_iva_orden.items()):
                                cols_tot[1 + idx_iva].metric(etiqueta, formato_cop(monto))
                        else:
                            cols_tot[1].metric("IVA", formato_cop(0))
                        cols_tot[-1].metric("Total a cobrar", formato_cop(gran_total))
                    else:
                        st.success(f"Total a cobrar al cliente: {formato_cop(gran_total)}")
                    
                    st.markdown("---")
                    
                    st.markdown("#### Exportar Documento")
                    
                    # Leer config del taller (logo, NIT, tel, dirección)
                    cfg = st.session_state.get("taller_config", {})
                    
                    # Cargar logo_path desde BD si no está en session_state
                    logo_path = cfg.get("logo_path")
                    if not logo_path:
                        with engine.connect() as conn_logo:
                            logo_row = conn_logo.execute(
                                text("SELECT logo_path FROM Usuarios WHERE id = :uid"),
                                {"uid": user_id}
                            ).fetchone()
                            logo_path = logo_row[0] if logo_row and logo_row[0] else None
                    
                    pdf_bytes = generar_pdf_orden_profesional(
                        taller_nombre=nombre_taller,
                        taller_nit=cfg.get("nit", ""),
                        taller_telefono=cfg.get("telefono", ""),
                        taller_direccion=cfg.get("direccion", ""),
                        taller_email=cfg.get("email", ""),
                        taller_logo_path=logo_path,
                        hoja_id=hoja_id,
                        fecha=fecha,
                        cliente=cliente,
                        cliente_nit=nit,
                        placa=placa,
                        estado=estado_actual,
                        df_items=df_trabajos,
                        total=gran_total,
                        subtotal=subtotal_orden if IVA_ACTIVO else None,
                        desglose_iva=desglose_iva_orden if IVA_ACTIVO else None
                    )
                    
                    st.download_button(
                        label="📄 Descargar Factura / Cotización en PDF",
                        data=pdf_bytes,
                        file_name=f"Orden_{hoja_id}_Placa_{placa}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                    
                    if not cfg:
                        st.caption("💡 Configura el logo y datos en **Configuración del Taller** para que aparezcan en el PDF.")

                    st.markdown("---")
                    st.markdown("#### Copiado Rápido de Ítems")
                    
                    for index, row in df_trabajos.iterrows():
                        col_i1, col_i2 = st.columns([3, 1])
                        with col_i1:
                            st.text(f"[{row['tipo_item']}] - {row['descripcion']} ({formato_cop(row['precio_venta'])})")
                        with col_i2:
                            st.code(row['descripcion'], language="text")
                else:
                    st.info("No hay trabajos registrados para esta orden todavía.")

            with tab_facturar_dian:
                st.subheader("Facturación Electrónica (DIAN)")

                if not tiene_fe_habilitada(user_id):
                    st.info(
                        "Esta función todavía no está habilitada para tu taller. "
                        "Contacta al administrador para activarla."
                    )
                else:
                    creds_fe = obtener_credenciales_alegra(user_id)
                    if not (creds_fe and creds_fe.alegra_email and creds_fe.alegra_token):
                        st.warning(
                            "Todavía no conectaste tu cuenta de Alegra. Ve a "
                            "**Configuración del Taller → Facturación Electrónica** para conectarla."
                        )
                    else:
                        with engine.connect() as conn_fe:
                            orden_fe = conn_fe.execute(text("""
                                SELECT factura_estado, factura_alegra_id, factura_prefijo, factura_numero,
                                       nota_credito_alegra_id
                                FROM Hojas_Trabajo WHERE id = :hid
                            """), {"hid": hoja_id}).fetchone()

                        factura_estado_fe = orden_fe[0] if orden_fe else None
                        numero_factura_fe = f"{orden_fe[2] or ''}{orden_fe[3] or ''}" if orden_fe else ""

                        if not factura_estado_fe:
                            st.markdown("Completa el método de pago para crear la factura electrónica de esta orden.")
                            if df_trabajos.empty:
                                st.warning("Esta orden no tiene ítems. Agrega al menos uno en 'Edición y Gestión' antes de facturar.")
                            else:
                                opciones_pago = ["Efectivo", "Transferencia", "Credito", "Mixto"]
                                tipo_pago_sel = st.selectbox("Método de pago", opciones_pago, key="tipo_pago_facturar")
                                fecha_venc_sel = None
                                if tipo_pago_sel == "Credito":
                                    fecha_venc_sel = st.date_input(
                                        "Fecha de vencimiento del crédito",
                                        value=datetime.today() + timedelta(days=30),
                                        key="fecha_venc_facturar"
                                    )
                                if st.button("Crear factura electrónica", type="primary", use_container_width=True):
                                    with st.spinner("Creando factura en Alegra..."):
                                        ok_f, msg_f = alegra_utils.facturar_orden(user_id, hoja_id, tipo_pago_sel, fecha_venc_sel)
                                    if ok_f:
                                        st.success(msg_f)
                                    else:
                                        st.error(msg_f)
                                    st.rerun()

                        elif factura_estado_fe == "abierta":
                            st.info(f"Factura creada (#{numero_factura_fe}) — todavía no se ha emitido ante la DIAN.")
                            pdf_mostrar_fe, _ = alegra_utils.refrescar_url_factura_orden(user_id, hoja_id)
                            if pdf_mostrar_fe:
                                st.link_button("Ver PDF (borrador)", pdf_mostrar_fe, use_container_width=True)
                            if st.button("Emitir a la DIAN", type="primary", use_container_width=True):
                                with st.spinner("Emitiendo ante la DIAN..."):
                                    ok_e, msg_e = alegra_utils.emitir_factura_dian_orden(user_id, hoja_id)
                                if ok_e:
                                    st.success(msg_e)
                                else:
                                    st.error(msg_e)
                                st.rerun()

                        elif factura_estado_fe == "emitida":
                            st.success(f"Factura electrónica emitida ante la DIAN (#{numero_factura_fe}).")
                            pdf_mostrar_fe, xml_mostrar_fe = alegra_utils.refrescar_url_factura_orden(user_id, hoja_id)
                            col_fpdf, col_fxml = st.columns(2)
                            if pdf_mostrar_fe:
                                col_fpdf.link_button("Ver PDF de la factura", pdf_mostrar_fe, use_container_width=True)
                            if xml_mostrar_fe:
                                col_fxml.link_button("Descargar XML (DIAN)", xml_mostrar_fe, use_container_width=True)

                            if orden_fe[4]:
                                st.markdown("---")
                                st.warning("Esta factura fue anulada mediante nota crédito.")
                                pdf_nc_fe, xml_nc_fe = alegra_utils.refrescar_url_nota_credito_orden(user_id, hoja_id)
                                col_ncpdf, col_ncxml = st.columns(2)
                                if pdf_nc_fe:
                                    col_ncpdf.link_button("Ver PDF de la Nota Crédito", pdf_nc_fe, use_container_width=True)
                                if xml_nc_fe:
                                    col_ncxml.link_button("Descargar XML (DIAN)", xml_nc_fe, use_container_width=True)

                        else:
                            st.error(f"Estado de facturación no reconocido: {factura_estado_fe}")

            if mostrar_tab_anular:
                with tab_anular:
                    st.subheader("Anular Factura Electrónica")
                    st.caption(
                        "Usa esto solo si el trabajo se anuló o devolvió después de facturado. "
                        "Genera una nota crédito ante la DIAN que anula la factura electrónica de esta orden."
                    )
                    st.warning(f"Vas a anular la factura #{numero_factura_actual} de esta orden. Esta acción no se puede deshacer.")
                    if st.button("Anular factura con nota crédito", type="primary", use_container_width=True):
                        with st.spinner("Emitiendo nota crédito..."):
                            ok_nc, msg_nc = alegra_utils.anular_factura_orden(user_id, hoja_id)
                        if ok_nc:
                            st.success(msg_nc)
                        else:
                            st.error(msg_nc)
                        st.rerun()

            with tab_editar:
                st.subheader("1. Cambio de Estado Operativo")
                col_est1, col_est2 = st.columns([2, 1])
                with col_est1:
                    estados_disponibles = ["Cotizar", "En revisión", "Esperando repuestos", "En reparación", "Listo para facturar", "Facturado"]
                    indice_actual = estados_disponibles.index(estado_actual) if estado_actual in estados_disponibles else 0
                    nuevo_estado = st.selectbox("Selecciona el nuevo estado", estados_disponibles, index=indice_actual)
                with col_est2:
                    st.write("") 
                    if st.button("Guardar Cambio de Estado", use_container_width=True):
                        try:
                            with engine.begin() as conn_est:
                                conn_est.execute(
                                    text("UPDATE Hojas_Trabajo SET estado = :est WHERE id = :hid"),
                                    {"est": nuevo_estado, "hid": hoja_id}
                                )
                            invalidar_cache_ordenes()
                            st.success("Estado actualizado correctamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                
                st.markdown("---")
                st.subheader("2. Gestión y Modificación de Ítems")
                if not df_trabajos.empty:
                    for index, row in df_trabajos.iterrows():
                        with st.container(border=True):
                            col_e1, col_e2, col_e3, col_e4 = st.columns([3, 2, 1, 1])
                            with col_e1:
                                st.write(f"**{row['tipo_item']}**: {row['descripcion']}")
                            with col_e2:
                                st.write(f"Valor: {formato_cop(row['precio_venta'])}")
                            with col_e3:
                                if st.button("Editar", key=f"edit_item_{row['id']}"):
                                    st.session_state[f"modo_edit_{row['id']}"] = True
                            with col_e4:
                                if st.button("Eliminar", key=f"del_{row['id']}"):
                                    try:
                                        with engine.begin() as conn_del:
                                            conn_del.execute(
                                                text("DELETE FROM Detalles_Orden WHERE id = :did"),
                                                {"did": row['id']}
                                            )
                                        invalidar_cache_ordenes()
                                        st.success("Ítem eliminado.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error al eliminar: {e}")

                            if st.session_state.get(f"modo_edit_{row['id']}", False):
                                with st.form(key=f"form_edit_item_{row['id']}"):
                                    st.markdown(f"Editando ítem #{row['id']}")
                                    nueva_desc = st.text_input("Nueva Descripción", value=row['descripcion'])
                                    nuevo_precio = st.number_input("Nuevo Precio ($)", min_value=0.0, step=5000.0, value=float(row['precio_venta']))

                                    opciones_iva_edit = ["Usar el default de su categoría"] + IVA_OPCIONES
                                    iva_tipo_actual = row.get('iva_tipo', None)
                                    idx_iva_edit = opciones_iva_edit.index(iva_tipo_actual) if iva_tipo_actual in IVA_OPCIONES else 0
                                    sel_iva_edit = st.selectbox("Impuesto (IVA) para este ítem", opciones_iva_edit, index=idx_iva_edit)
                                    
                                    col_fe1, col_fe2 = st.columns(2)
                                    with col_fe1:
                                        if st.form_submit_button("Guardar Cambios", type="primary"):
                                            nuevo_iva_tipo = None if sel_iva_edit == "Usar el default de su categoría" else sel_iva_edit
                                            try:
                                                with engine.begin() as conn_upd:
                                                    conn_upd.execute(
                                                        text("""
                                                            UPDATE Detalles_Orden
                                                            SET descripcion = :desc, precio_venta = :precio, iva_tipo = :iva_tipo
                                                            WHERE id = :did
                                                        """),
                                                        {"desc": nueva_desc, "precio": float(nuevo_precio),
                                                         "iva_tipo": nuevo_iva_tipo, "did": row['id']}
                                                    )
                                                invalidar_cache_ordenes()
                                                st.session_state[f"modo_edit_{row['id']}"] = False
                                                st.success("Ítem actualizado y sincronizado en todo el sistema.")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Error al actualizar: {e}")
                                    with col_fe2:
                                        if st.form_submit_button("Cancelar"):
                                            st.session_state[f"modo_edit_{row['id']}"] = False
                                            st.rerun()
                else:
                    st.warning("No hay ítems para modificar.")

                st.markdown("---")
                st.subheader("3. Adición de Nuevos Ítems")
                
                with st.expander("Desplegar formulario para agregar trabajo o repuesto"):
                    tab_mo, tab_rep = st.tabs(["Mano de Obra", "Repuesto"])

                    opciones_iva_nuevo = ["Usar el default de su categoría"] + IVA_OPCIONES
                    
                    with tab_mo:
                        desc_mo = st.text_input("Descripción", key="e_desc_mo")
                        mec_sel = st.selectbox("Mecánico", options=list(dict_mecanicos.keys()), key="e_mec_mo") if dict_mecanicos else None
                        venta_mo = st.number_input("Cobro Cliente ($)", min_value=0, step=5000, key="e_venta_mo")
                        sel_iva_mo = st.selectbox("Impuesto (IVA) para este ítem", opciones_iva_nuevo, index=0, key="e_iva_mo",
                                                   help=f"El default configurado para Mano de Obra es: {IVA_TIPO_DEFAULT_MO}")
                        if st.button("Guardar Trabajo", use_container_width=True):
                            if desc_mo and venta_mo > 0 and mec_sel:
                                iva_tipo_mo = None if sel_iva_mo == "Usar el default de su categoría" else sel_iva_mo
                                try:
                                    with engine.begin() as conn_mo:
                                        conn_mo.execute(
                                            text('''
                                                INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, mecanico_id, precio_venta, iva_tipo)
                                                VALUES (:hid, 'Mano de Obra', :desc, :mid, :pvp, :iva_tipo)
                                            '''),
                                            {"hid": hoja_id, "desc": desc_mo, "mid": dict_mecanicos[mec_sel],
                                             "pvp": float(venta_mo), "iva_tipo": iva_tipo_mo}
                                        )
                                    invalidar_cache_ordenes()
                                    st.success("Trabajo agregado con éxito.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                            else:
                                st.error("Completa la descripción, el precio y asegúrate de tener mecánicos registrados.")
                            
                    with tab_rep:
                        origen_rep_exp = st.radio(
                            "Origen del Repuesto:",
                            ["Comprado afuera (Encargo)", "Tomado del Almacén Propio"],
                            horizontal=True,
                            key="origen_rep_exp"
                        )

                        if origen_rep_exp == "Comprado afuera (Encargo)":
                            desc_rep = st.text_input("Nombre Repuesto", key="e_desc_rep_ext")
                            costo_rep = st.number_input("Costo Compra ($)", min_value=0, step=1000, key="e_costo_rep_ext")
                            venta_rep = st.number_input("Precio Venta ($)", min_value=0, step=1000, key="e_venta_rep_ext")
                            sel_iva_rep_ext = st.selectbox("Impuesto (IVA) para este ítem", opciones_iva_nuevo, index=0, key="e_iva_rep_ext",
                                                            help=f"El default configurado para Repuestos es: {IVA_TIPO_DEFAULT_REP}")
                            
                            if st.button("Guardar Repuesto Externo", use_container_width=True):
                                if desc_rep and venta_rep > 0:
                                    iva_tipo_rep_ext = None if sel_iva_rep_ext == "Usar el default de su categoría" else sel_iva_rep_ext
                                    try:
                                        with engine.begin() as conn_rep:
                                            conn_rep.execute(
                                                text('''
                                                    INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, costo_compra, precio_venta, iva_tipo)
                                                    VALUES (:hid, 'Repuesto', :desc, :costo, :pvp, :iva_tipo)
                                                '''),
                                                {"hid": hoja_id, "desc": desc_rep, "costo": float(costo_rep),
                                                 "pvp": float(venta_rep), "iva_tipo": iva_tipo_rep_ext}
                                            )
                                        invalidar_cache_ordenes()
                                        st.success("Repuesto agregado con éxito.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                                else:
                                    st.error("Completa la descripción y el precio de venta.")
                        else:
                            with engine.connect() as conn_inv:
                                prods = conn_inv.execute(
                                    text("SELECT id, nombre_producto, stock_actual, costo_compra, precio_venta, iva_tipo FROM Inventario WHERE usuario_id = :uid AND stock_actual > 0 ORDER BY nombre_producto ASC"),
                                    {"uid": user_id}
                                ).fetchall()

                            if prods:
                                dict_prods = {f"{p[1]} (Stock: {p[2]} un) - PVP: {formato_cop(p[4])}": p for p in prods}
                                prod_sel_key = st.selectbox("Selecciona un producto del almacén:", options=list(dict_prods.keys()), key="exp_prod_sel")
                                prod_data = dict_prods[prod_sel_key]

                                col_exp_inv1, col_exp_inv2 = st.columns(2)
                                with col_exp_inv1:
                                    cant_usar_exp = st.number_input("Cantidad a Usar", min_value=1, max_value=int(prod_data[2]), value=1, step=1, key="exp_cant_usar")
                                with col_exp_inv2:
                                    pvp_unitario_exp = float(prod_data[4])
                                    st.markdown(f"**Total Cobro:** {formato_cop(pvp_unitario_exp * cant_usar_exp)}")

                                iva_tipo_prod = prod_data[5] if prod_data[5] else "Excluido"
                                st.caption(f"🧾 Impuesto de este producto (configurado en Inventario): **{iva_tipo_prod}**")

                                if st.button("Guardar Repuesto de Almacén", use_container_width=True):
                                    try:
                                        with engine.begin() as conn_rep_inv:
                                            conn_rep_inv.execute(
                                                text('''
                                                    INSERT INTO Detalles_Orden (hoja_id, tipo_item, descripcion, costo_compra, precio_venta, iva_tipo)
                                                    VALUES (:hid, 'Repuesto', :desc, :costo, :pvp, :iva_tipo)
                                                '''),
                                                {
                                                    "hid": hoja_id, 
                                                    "desc": f"{prod_data[1]} (x{cant_usar_exp})", 
                                                    "costo": float(prod_data[3]) * cant_usar_exp, 
                                                    "pvp": pvp_unitario_exp * cant_usar_exp,
                                                    "iva_tipo": prod_data[5]
                                                }
                                            )
                                            conn_rep_inv.execute(
                                                text("UPDATE Inventario SET stock_actual = stock_actual - :cant WHERE id = :inv_id"),
                                                {"cant": cant_usar_exp, "inv_id": prod_data[0]}
                                            )
                                        invalidar_cache_ordenes()
                                        invalidar_cache_inventario()
                                        st.success("Repuesto asignado y descontado del almacén.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error al asignar repuesto del almacén: {e}")
                            else:
                                st.info("No tienes productos con stock disponible en tu almacén.")
    else:
        st.error("Por favor, ingresa un número de orden válido.")
