import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta
from sqlalchemy import text
from db import obtener_conexion, init_db, mensaje_error_amigable
from queries import (
    obtener_catalogos, obtener_config_taller, invalidar_cache_ordenes, invalidar_cache_inventario,
    tiene_fe_habilitada, obtener_credenciales_factus, marcar_entrega,
)
from io import BytesIO
from pdf_utils import generar_pdf_orden_profesional, calcular_totales_orden, IVA_OPCIONES
import factus_utils
import excel_utils

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

    .expediente-card {
        background-color: #f8fafc;
        padding: 16px;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        margin-bottom: 10px;
    }

    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out !important; }
    div[data-testid="stVerticalBlock"] > div { animation: fade-in-up 0.5s ease-out !important; }
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


@st.cache_data(ttl=30, show_spinner=False)
def _consultar_historial_cacheado(sql, params):
    # El historial se volvía a consultar (hasta 5000 filas para el export)
    # en CADA rerun de esta página, aunque el usuario solo hubiera tocado
    # algo en otra sección (ej. Expediente). Cacheado por el SQL + filtros
    # exactos: si no cambiaron, se reusa el resultado.
    engine_local = obtener_conexion()
    with engine_local.connect() as conn:
        return pd.read_sql_query(text(sql), con=conn, params=params)


def _invalidar_caches_orden():
    # invalidar_cache_ordenes() ya limpiaba el resto de vistas compartidas;
    # el historial de esta página tiene su propio caché local y hay que
    # limpiarlo también tras cualquier escritura, o mostraría datos viejos
    # hasta que expire el TTL.
    invalidar_cache_ordenes()
    _consultar_historial_cacheado.clear()
    _generar_excel_historial_cacheado.clear()


@st.cache_data(ttl=30, show_spinner=False)
def _generar_excel_historial_cacheado(sql, params, nombre_taller):
    # El Excel (hasta 5000 filas, con estilos por celda) se reconstruía en
    # CADA rerun de esta página aunque el usuario solo hubiera tocado algo
    # en otra sección (ej. Expediente). Se cachea junto con la consulta
    # para que solo se regenere cuando cambian los filtros o vence el TTL.
    df_export = _consultar_historial_cacheado(sql, params)
    return df_export, excel_utils.generar_excel_tabla(
        df_export, "Historial de Órdenes", nombre_taller,
        columnas_moneda=["Total"], nombre_hoja="Órdenes", columna_total="Total"
    )


@st.cache_data(show_spinner=False)
def _generar_pdf_orden_cacheado(**kwargs):
    # El PDF se regeneraba en CADA rerun de la página (cualquier clic en
    # este módulo la vuelve a correr entera), aunque nada de la orden
    # hubiera cambiado. Cacheado por los mismos datos que recibe: si la
    # orden sigue igual, se reusa el PDF ya generado en vez de rehacerlo.
    return generar_pdf_orden_profesional(**kwargs)

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
        SELECT h.numero_orden as "N° Orden", date(h.fecha_ingreso) as "Fecha",
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
        
        sql_final_list = sql_list_select + " " + " ".join(sql_conditions) + " GROUP BY h.id, h.numero_orden, h.fecha_ingreso, h.placa, e.razon_social, h.estado ORDER BY h.id DESC LIMIT :limit OFFSET :offset"
        params_exp["limit"] = REGISTROS_POR_PAGINA
        params_exp["offset"] = offset

        df_lista = _consultar_historial_cacheado(sql_final_list, params_exp)

        st.dataframe(
            df_lista.style.format({'Total': lambda x: formato_cop(x)}),
            width='stretch', hide_index=True
        )

        # El Excel exporta TODOS los resultados que coinciden con los filtros
        # (no solo la página visible en pantalla) — tope de 5000 filas, más
        # que suficiente para el historial de cualquier taller.
        sql_export = sql_list_select + " " + " ".join(sql_conditions) + " GROUP BY h.id, h.numero_orden, h.fecha_ingreso, h.placa, e.razon_social, h.estado ORDER BY h.id DESC LIMIT 5000"
        _df_export, excel_historial = _generar_excel_historial_cacheado(sql_export, params_exp, nombre_taller)

        st.download_button(
            f"📥 Descargar Excel ({total_registros} orden(es) que coinciden con los filtros)",
            data=excel_historial,
            file_name=f"Historial_Ordenes_{datetime.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No se encontraron órdenes que coincidan con los filtros seleccionados.")
else:
    st.warning("Por favor selecciona un rango de fechas válido.")

st.markdown("---")

st.subheader("Abrir Expediente Específico")
st.markdown("Ingresa el número de orden para consultar detalles, auditar o modificar registros.")

orden_busqueda = st.text_input("Número de Orden", key="orden_busqueda_valor")

if orden_busqueda:
    if orden_busqueda.isdigit():
        numero_orden_buscado = int(orden_busqueda)

        with engine.connect() as conn:
            query_vehiculo = text('''
                SELECT h.id, h.numero_orden, h.placa, h.estado, h.fecha_ingreso, e.razon_social, e.nit,
                       h.factura_estado, h.nota_credito_reference_code, h.factura_prefijo, h.factura_numero,
                       h.tipo_pago, h.fecha_entrega
                FROM Hojas_Trabajo h
                JOIN Empresas_Clientes e ON h.empresa_id = e.id
                WHERE h.numero_orden = :nro AND h.usuario_id = :uid
            ''')
            vehiculo = conn.execute(query_vehiculo, {"nro": numero_orden_buscado, "uid": user_id}).fetchone()

        if not vehiculo:
            st.warning(f"No se encontró ninguna orden con el número #{numero_orden_buscado} en tu taller.")
        else:
            (hoja_id, numero_orden_actual, placa, estado_actual, fecha, cliente, nit, factura_estado_actual,
             nota_credito_actual, factura_prefijo_actual, factura_numero_actual, tipo_pago_actual,
             fecha_entrega_actual) = vehiculo
            numero_factura_actual = f"{factura_prefijo_actual or ''}{factura_numero_actual or ''}"

            st.markdown(f"### Expediente de Orden #{numero_orden_actual} | Placa: {placa}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Cliente", cliente)
            col2.metric("NIT", nit)
            col3.metric("Estado Actual", estado_actual)

            col_ent1, col_ent2 = st.columns([3, 1])
            with col_ent1:
                if fecha_entrega_actual:
                    st.success(f"🚗 Vehículo entregado el {fecha_entrega_actual}.")
                else:
                    st.info("🅿️ Vehículo todavía no se ha marcado como entregado.")
            with col_ent2:
                if fecha_entrega_actual:
                    if st.button("Deshacer entrega", width='stretch'):
                        marcar_entrega(user_id, hoja_id, False)
                        st.rerun()
                else:
                    if st.button("Marcar como Entregado", type="primary", width='stretch'):
                        marcar_entrega(user_id, hoja_id, True)
                        st.rerun()

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

            # Anular una factura ya emitida solo se puede hacer desde la
            # página Anulaciones (no desde aquí), para que quede centralizado
            # en un único lugar del sistema.
            nombres_tabs = ["Detalles y Copia de Ítems", "Facturar", "Edición y Gestión"]
            tabs_creados = st.tabs(nombres_tabs)
            tab_factura = tabs_creados[0]
            tab_facturar_dian = tabs_creados[1]
            tab_editar = tabs_creados[2]
            
            with tab_factura:
                if not df_trabajos.empty:
                    df_mostrar = df_trabajos[['tipo_item', 'descripcion', 'mecanico', 'precio_venta', 'iva_tipo']].copy()
                    df_mostrar['iva_tipo'] = df_mostrar['iva_tipo'].fillna('(default de categoría)')
                    df_mostrar.columns = ['Tipo', 'Descripción', 'Técnico', 'Cobro al Cliente', 'Impuesto (IVA)']
                    st.dataframe(
                        df_mostrar.style.format({'Cobro al Cliente': lambda x: formato_cop(x)}),
                        width='stretch', hide_index=True
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
                    
                    # Leer config del taller (logo, NIT, tel, dirección) — persistida
                    # en BD, ya no depende de session_state (se perdía al recargar).
                    logo_path = _config_taller[3] if _config_taller and _config_taller[3] else None
                    taller_nit = _config_taller[8] if _config_taller and len(_config_taller) > 8 and _config_taller[8] else ""
                    taller_telefono = _config_taller[9] if _config_taller and len(_config_taller) > 9 and _config_taller[9] else ""
                    taller_direccion_raw = _config_taller[10] if _config_taller and len(_config_taller) > 10 and _config_taller[10] else ""
                    taller_ciudad = _config_taller[11] if _config_taller and len(_config_taller) > 11 and _config_taller[11] else ""
                    taller_direccion = f"{taller_direccion_raw}, {taller_ciudad}".strip(", ") if taller_ciudad else taller_direccion_raw
                    taller_email = _config_taller[2] if _config_taller and _config_taller[2] else ""

                    if not taller_nit:
                        st.warning(
                            "Tu taller todavía no tiene NIT configurado — la factura saldrá sin ese dato. "
                            "Complétalo en Configuración > Datos del Taller."
                        )

                    pdf_bytes = _generar_pdf_orden_cacheado(
                        taller_nombre=nombre_taller,
                        taller_nit=taller_nit,
                        taller_telefono=taller_telefono,
                        taller_direccion=taller_direccion,
                        taller_email=taller_email,
                        taller_logo_path=logo_path,
                        hoja_id=numero_orden_actual,
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
                        file_name=f"Orden_{numero_orden_actual}_Placa_{placa}.pdf",
                        mime="application/pdf",
                        type="primary",
                        width='stretch'
                    )
                    
                    if not _config_taller:
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
                    creds_fe = obtener_credenciales_factus(user_id)
                    if not (creds_fe and creds_fe.factus_client_id and creds_fe.factus_client_secret):
                        st.warning(
                            "Todavía no conectaste tu cuenta de Factus. Ve a "
                            "**Configuración del Taller → Facturación Electrónica** para conectarla."
                        )
                    else:
                        placeholder_fe = st.empty()

                        def _dibujar_estado_factura():
                            # Vuelve a consultar y dibujar esta pestaña con el
                            # estado más reciente, en la MISMA ejecución del
                            # script (se llama a sí misma tras facturar con
                            # éxito) - así se evita un st.rerun() de página
                            # completa después de una llamada a Factus que ya
                            # de por sí tarda unos segundos. placeholder_fe ya
                            # reemplaza su contenido anterior solo al volver a
                            # dibujar adentro, así que no queda el formulario
                            # viejo apilado debajo del mensaje de éxito.
                            with placeholder_fe.container():
                                with engine.connect() as conn_fe:
                                    orden_fe = conn_fe.execute(text("""
                                        SELECT factura_estado, factura_reference_code, factura_prefijo, factura_numero,
                                               nota_credito_reference_code
                                        FROM Hojas_Trabajo WHERE id = :hid
                                    """), {"hid": hoja_id}).fetchone()

                                factura_estado_fe = orden_fe[0] if orden_fe else None
                                numero_factura_fe = f"{orden_fe[2] or ''}{orden_fe[3] or ''}" if orden_fe else ""

                                if not factura_estado_fe:
                                    st.markdown("Completa el método de pago para facturar y emitir esta orden ante la DIAN.")
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
                                        with st.form("form_facturar_electronica", clear_on_submit=False):
                                            col_notas, col_oc = st.columns(2)
                                            with col_notas:
                                                notas_sel = st.text_area(
                                                    "Notas (opcional)", key="notas_facturar",
                                                    help="Aparece impresa en el PDF de la factura."
                                                )
                                            with col_oc:
                                                orden_compra_sel = st.text_input(
                                                    "Orden de compra (opcional)", key="orden_compra_facturar",
                                                    help="Número de orden de compra del cliente, si tiene una."
                                                )
                                            crear_factura_click = st.form_submit_button(
                                                "Facturar y Emitir a la DIAN", type="primary", width='stretch'
                                            )
                                        if crear_factura_click:
                                            with st.spinner("Facturando y timbrando ante la DIAN..."):
                                                ok_f, msg_f = factus_utils.facturar_orden(
                                                    user_id, hoja_id, tipo_pago_sel, fecha_venc_sel,
                                                    notas=notas_sel or None, orden_compra=orden_compra_sel or None,
                                                )
                                            if ok_f:
                                                st.success(msg_f)
                                                _dibujar_estado_factura()
                                            else:
                                                st.error(msg_f)

                                elif factura_estado_fe == "emitida":
                                    st.success(f"Factura electrónica emitida ante la DIAN (#{numero_factura_fe}).")
                                    pdf_mostrar_fe, xml_mostrar_fe = factus_utils.refrescar_url_factura_orden(user_id, hoja_id)
                                    col_fpdf, col_fxml = st.columns(2)
                                    factus_utils.mostrar_documento(
                                        col_fpdf, "Ver PDF de la factura", pdf_mostrar_fe,
                                        f"Factura_Orden_{numero_orden_actual}.pdf", "application/pdf"
                                    )
                                    factus_utils.mostrar_documento(
                                        col_fxml, "Descargar XML (DIAN)", xml_mostrar_fe,
                                        f"Factura_Orden_{numero_orden_actual}.xml", "application/xml"
                                    )

                                    if orden_fe[4]:
                                        st.markdown("---")
                                        st.warning("Esta factura fue anulada mediante nota crédito.")
                                        pdf_nc_fe, xml_nc_fe = factus_utils.refrescar_url_nota_credito_orden(user_id, hoja_id)
                                        col_ncpdf, col_ncxml = st.columns(2)
                                        factus_utils.mostrar_documento(
                                            col_ncpdf, "Ver PDF de la Nota Crédito", pdf_nc_fe,
                                            f"NotaCredito_Orden_{numero_orden_actual}.pdf", "application/pdf"
                                        )
                                        factus_utils.mostrar_documento(
                                            col_ncxml, "Descargar XML (DIAN)", xml_nc_fe,
                                            f"NotaCredito_Orden_{numero_orden_actual}.xml", "application/xml"
                                        )
                                    else:
                                        st.caption(
                                            "¿Necesitas anular esta factura? Hazlo desde la página "
                                            "**Anulaciones**, buscando esta misma orden."
                                        )

                                else:
                                    st.error(f"Estado de facturación no reconocido: {factura_estado_fe}")

                        _dibujar_estado_factura()

            with tab_editar:
                if factura_estado_actual:
                    st.warning(
                        "Esta orden ya tiene una factura electrónica creada en Factus y no se puede "
                        "editar (ítems, precios ni estado): cambiar algo acá ya no coincidiría con lo "
                        "que quedó facturado. Si necesitas corregirla, anula la factura primero desde "
                        "la página **Anulaciones**."
                    )
                    st.stop()

                st.subheader("1. Cambio de Estado Operativo")
                col_est1, col_est2 = st.columns([2, 1])
                with col_est1:
                    estados_disponibles = ["Cotizar", "En revisión", "Esperando repuestos", "En reparación", "Listo para facturar", "Facturado"]
                    indice_actual = estados_disponibles.index(estado_actual) if estado_actual in estados_disponibles else 0
                    nuevo_estado = st.selectbox("Selecciona el nuevo estado", estados_disponibles, index=indice_actual)
                with col_est2:
                    st.write("") 
                    if st.button("Guardar Cambio de Estado", width='stretch'):
                        try:
                            with engine.begin() as conn_est:
                                conn_est.execute(
                                    text("UPDATE Hojas_Trabajo SET estado = :est WHERE id = :hid"),
                                    {"est": nuevo_estado, "hid": hoja_id}
                                )
                            _invalidar_caches_orden()
                            st.success("Estado actualizado correctamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(mensaje_error_amigable(e, "actualizar el estado"))
                
                st.markdown("---")
                st.subheader("2. Gestión y Modificación de Ítems")
                if not df_trabajos.empty:
                    # Sin st.container(border=True) por fila - más liviano de
                    # volver a dibujar en cada clic, separado con una línea.
                    for index, row in df_trabajos.iterrows():
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
                                st.session_state[f"del_confirm_item_{row['id']}"] = True

                        if st.session_state.get(f"del_confirm_item_{row['id']}", False):
                            col_di1, col_di2, col_di3 = st.columns([2, 1, 1])
                            col_di1.warning(f"¿Eliminar **{row['descripcion']}** de esta orden?")
                            with col_di2:
                                if st.button("Sí, eliminar", key=f"yes_del_item_{row['id']}", type="primary", width='stretch'):
                                    try:
                                        with engine.begin() as conn_del:
                                            conn_del.execute(
                                                text("DELETE FROM Detalles_Orden WHERE id = :did"),
                                                {"did": row['id']}
                                            )
                                        _invalidar_caches_orden()
                                        st.session_state[f"del_confirm_item_{row['id']}"] = False
                                        st.success("Ítem eliminado.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(mensaje_error_amigable(e, "eliminar el ítem"))
                            with col_di3:
                                if st.button("Cancelar", key=f"no_del_item_{row['id']}", width='stretch'):
                                    st.session_state[f"del_confirm_item_{row['id']}"] = False
                                    st.rerun()

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
                                            _invalidar_caches_orden()
                                            st.session_state[f"modo_edit_{row['id']}"] = False
                                            st.success("Ítem actualizado y sincronizado en todo el sistema.")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(mensaje_error_amigable(e, "actualizar el ítem"))
                                with col_fe2:
                                    if st.form_submit_button("Cancelar"):
                                        st.session_state[f"modo_edit_{row['id']}"] = False
                                        st.rerun()
                        st.divider()
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
                        if st.button("Guardar Trabajo", width='stretch'):
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
                                    _invalidar_caches_orden()
                                    st.success("Trabajo agregado con éxito.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(mensaje_error_amigable(e, "agregar el trabajo"))
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
                            
                            if st.button("Guardar Repuesto Externo", width='stretch'):
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
                                        _invalidar_caches_orden()
                                        st.success("Repuesto agregado con éxito.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(mensaje_error_amigable(e, "agregar el repuesto"))
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

                                if st.button("Guardar Repuesto de Almacén", width='stretch'):
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
                                        _invalidar_caches_orden()
                                        invalidar_cache_inventario()
                                        st.success("Repuesto asignado y descontado del almacén.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(mensaje_error_amigable(e, "asignar el repuesto del almacén"))
                            else:
                                st.info("No tienes productos con stock disponible en tu almacén.")
    else:
        st.error("Por favor, ingresa un número de orden válido.")
