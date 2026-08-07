import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion, init_db, mensaje_error_amigable
from queries import invalidar_cache_inventario, obtener_config_taller
from pdf_utils import IVA_OPCIONES

st.set_page_config(page_title="Inventario y Almacén", layout="wide")
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
    [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.15s ease-out; }
    </style>
""", unsafe_allow_html=True)

if "auth" not in st.session_state:
    st.session_state.auth = {"logged": False, "user_id": None, "nombre_taller": None}
if not st.session_state.auth["logged"]:
    st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
    st.stop()

if st.session_state.auth.get("rol") == "patio":
    st.warning("🔒 Tu usuario solo tiene acceso al módulo de Recepción de Vehículos.")
    st.stop()

engine = obtener_conexion()
user_id = st.session_state.auth["user_id"]
nombre_taller = st.session_state.auth["nombre_taller"]

UNIDADES = ["Unidad", "kg", "g", "lb", "m", "cm", "vara", "pie",
            "L", "mL", "galón", "Docena", "Caja", "Bulto", "Rollo",
            "Paquete", "m²", "m³"]

# Config del taller cacheada (antes era una consulta cruda sin caché
# repetida en cada rerun de esta página)
_config_taller = obtener_config_taller(user_id)
IVA_TIPO_DEFAULT = _config_taller[7] if _config_taller and _config_taller[7] in IVA_OPCIONES else "Excluido"

def formato_cop(numero):
    return f"${float(numero):,.0f}".replace(",", ".")

def formato_cant(numero, unidad="Unidad"):
    unidades_decimales = ["kg", "g", "lb", "m", "cm", "vara", "pie",
                          "L", "mL", "galón", "m²", "m³"]
    if unidad in unidades_decimales:
        return f"{float(numero):.3f} {unidad}".rstrip('0').rstrip('.')
    return f"{int(numero)} {unidad}"

def calcular_precio_con_iva(precio, iva_tipo):
    precio = float(precio)
    if iva_tipo == "IVA 19%":
        return round(precio * 1.19, 0)
    elif iva_tipo == "IVA 5%":
        return round(precio * 1.05, 0)
    return precio  # Excluido o Exento

LIMITE_FILAS = 100

@st.cache_data(ttl=60)
def obtener_metricas_inventario(uid):
    engine = obtener_conexion()
    with engine.connect() as conn:
        row = conn.execute(text('''
            SELECT
                COALESCE(SUM(stock_actual * costo_compra), 0) AS val_costo,
                COALESCE(SUM(stock_actual * precio_venta), 0) AS val_venta,
                COALESCE(SUM(CASE WHEN stock_actual > 0 AND stock_actual <= stock_minimo THEN 1 ELSE 0 END), 0) AS por_agotarse,
                COALESCE(SUM(CASE WHEN stock_actual <= 0 THEN 1 ELSE 0 END), 0) AS agotados,
                COUNT(*) AS total_productos
            FROM Inventario WHERE usuario_id = :uid
        '''), {"uid": uid}).fetchone()
    return row.val_costo, row.val_venta, row.por_agotarse, row.agotados, row.total_productos


def obtener_inventario_filtrado(uid, busqueda, limite):
    engine = obtener_conexion()
    params = {"uid": uid, "limit": limite}
    cond = ""
    if busqueda:
        cond = "AND (nombre_producto ILIKE :busq OR codigo_ref ILIKE :busq)" \
               if "postgres" in str(engine.url) else \
               "AND (nombre_producto LIKE :busq OR codigo_ref LIKE :busq)"
        params["busq"] = f"%{busqueda}%"
    with engine.connect() as conn:
        return pd.read_sql_query(text(f'''
            SELECT id, nombre_producto, codigo_ref, unidad_medida,
                   stock_actual, stock_minimo, costo_compra, precio_venta, iva_tipo
            FROM Inventario
            WHERE usuario_id = :uid {cond}
            ORDER BY nombre_producto ASC LIMIT :limit
        '''), con=conn, params=params)


st.title("Inventario de Almacén")
st.markdown(f"Control de stock de repuestos e insumos para: **{nombre_taller}**")
st.markdown("---")

tab_stock, tab_nuevo, tab_entradas = st.tabs([
    "Stock Actual y Alertas",
    "Agregar Producto al Almacén",
    "Entradas de Mercancía 🤖"
])

# ==========================================
# TAB 1: STOCK ACTUAL
# ==========================================
with tab_stock:
    val_costo, val_venta, por_agotarse, agotados, total_productos = obtener_metricas_inventario(user_id)

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Inversión en Stock (Costo)", formato_cop(val_costo))
    col_m2.metric("Valor Comercial (Venta)", formato_cop(val_venta))
    col_m3.metric("Por Agotarse (Alerta)", por_agotarse)
    col_m4.metric("Agotados (Sin Stock)", agotados)
    st.markdown("---")

    if total_productos == 0:
        st.info("Aún no tienes repuestos o insumos registrados en el almacén de tu taller.")
    else:
        st.subheader("Gestión de Productos en Stock")
        busqueda = st.text_input(
            "Buscar por nombre o código de referencia",
            placeholder="Ej: filtro de aceite, cable #12...",
            help=f"Sin búsqueda se muestran los primeros {LIMITE_FILAS} productos."
        )

        df_inv = obtener_inventario_filtrado(user_id, busqueda.strip(), LIMITE_FILAS)

        if df_inv.empty:
            st.warning("No se encontraron productos que coincidan con la búsqueda.")
        else:
            if len(df_inv) == LIMITE_FILAS and total_productos > LIMITE_FILAS:
                st.caption(f"⚠️ Mostrando los primeros {LIMITE_FILAS} de {total_productos} productos.")

            st.caption("Edita directamente en la tabla y haz clic en guardar.")

            df_show = df_inv.copy()
            df_show['codigo_ref'] = df_show['codigo_ref'].fillna("").astype(str).replace("None", "")
            df_show['unidad_medida'] = df_show['unidad_medida'].fillna("Unidad")
            df_show['iva_tipo'] = df_show['iva_tipo'].apply(lambda v: v if v in IVA_OPCIONES else "Excluido")

            # Columnas calculadas (solo lectura)
            df_show['precio_con_iva'] = df_show.apply(
                lambda r: calcular_precio_con_iva(r['precio_venta'], r['iva_tipo']), axis=1
            )
            df_show['ganancia'] = (df_show['precio_venta'] - df_show['costo_compra']).round(0)
            df_show['pct_ganancia'] = df_show.apply(
                lambda r: round((r['ganancia'] / r['costo_compra']) * 100, 1)
                if r['costo_compra'] > 0 else 0.0, axis=1
            )

            df_editado = st.data_editor(
                df_show,
                hide_index=True,
                use_container_width=True,
                disabled=["id", "precio_con_iva", "ganancia", "pct_ganancia"],
                column_config={
                    "id": None,
                    "nombre_producto": "Producto / Repuesto",
                    "codigo_ref": st.column_config.TextColumn(
                        "Código / Ref / Barras",
                        help="Escanea el código de barras aquí"
                    ),
                    "unidad_medida": st.column_config.SelectboxColumn(
                        "Unidad", options=UNIDADES,
                        help="Ej: kg para puntillas, m para cable, Unidad para filtros"
                    ),
                    "stock_actual": st.column_config.NumberColumn(
                        "Stock Actual", min_value=0, step=0.001, format="%.3f"
                    ),
                    "stock_minimo": st.column_config.NumberColumn(
                        "Stock Mínimo", min_value=0, step=0.001, format="%.3f"
                    ),
                    "costo_compra": st.column_config.NumberColumn("Costo ($)", format="$%,d"),
                    "precio_venta": st.column_config.NumberColumn("Precio sin IVA ($)", format="$%,d"),
                    "precio_con_iva": st.column_config.NumberColumn("Precio con IVA ($)", format="$%,d"),
                    "ganancia": st.column_config.NumberColumn("Ganancia ($)", format="$%,d"),
                    "pct_ganancia": st.column_config.NumberColumn("% Ganancia", format="%.1f%%"),
                    "iva_tipo": st.column_config.SelectboxColumn(
                        "Impuesto (IVA)", options=IVA_OPCIONES,
                        help="Tipo de IVA de este producto."
                    ),
                },
                key=f"editor_inv_{busqueda}"
            )

            if st.button("Guardar Cambios de Inventario", type="primary"):
                try:
                    with engine.begin() as conn_upd:
                        for idx, row in df_editado.iterrows():
                            conn_upd.execute(text("""
                                UPDATE Inventario
                                SET nombre_producto = :nom, codigo_ref = :ref,
                                    unidad_medida = :um,
                                    stock_actual = :st_act, stock_minimo = :st_min,
                                    costo_compra = :costo, precio_venta = :pvp,
                                    iva_tipo = :iva_tipo
                                WHERE id = :id AND usuario_id = :uid
                            """), {
                                "nom": row['nombre_producto'],
                                "ref": row['codigo_ref'] or None,
                                "um": row['unidad_medida'],
                                "st_act": float(row['stock_actual']),
                                "st_min": float(row['stock_minimo']),
                                "costo": float(row['costo_compra']),
                                "pvp": float(row['precio_venta']),
                                "iva_tipo": row['iva_tipo'],
                                "id": int(row['id']),
                                "uid": user_id
                            })
                    obtener_metricas_inventario.clear()
                    invalidar_cache_inventario()
                    st.success("Inventario actualizado y sincronizado.")
                    st.rerun()
                except Exception as e:
                    st.error(mensaje_error_amigable(e, "actualizar el inventario"))

# ==========================================
# TAB 2: REGISTRAR NUEVO PRODUCTO
# ==========================================
with tab_nuevo:
    st.subheader("Registrar Nuevo Producto o Insumo")
    st.caption("💡 Puedes escanear el código de barras en el campo 'Código o Referencia'.")

    with st.form("form_nuevo_producto", clear_on_submit=True):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            nom_p = st.text_input("Nombre del Repuesto / Insumo")
            ref_p = st.text_input(
                "Código / Referencia / Código de Barras",
                placeholder="Escanea con el lector o escribe manualmente"
            )
            unidad_p = st.selectbox("Unidad de Medida", options=UNIDADES,
                                    help="Selecciona cómo se mide/vende este producto")
            iva_tipo_p = st.selectbox(
                "Impuesto (IVA) de este producto",
                options=IVA_OPCIONES,
                index=IVA_OPCIONES.index(IVA_TIPO_DEFAULT),
                help="Ej: 'Excluido' para aceite u otros exentos, 'IVA 19%' para un repuesto gravado."
            )
            hints = {
                "kg": "Ej: 2.5 kg de puntillas",
                "m": "Ej: 3.5 m de cable eléctrico",
                "L": "Ej: 1.5 L de pintura",
                "vara": "Ej: 2 varas de varilla",
                "Bulto": "Ej: 3 bultos de cemento",
            }
            if unidad_p in hints:
                st.caption(f"💡 {hints[unidad_p]}")

        with col_p2:
            unidades_dec = ["kg", "g", "lb", "m", "cm", "vara", "pie", "L", "mL", "galón", "m²", "m³"]
            if unidad_p in unidades_dec:
                stk_p = st.number_input(f"Cantidad Inicial en Stock ({unidad_p})",
                                         min_value=0.0, value=1.0, step=0.5)
                stk_min_p = st.number_input(f"Stock Mínimo (Alerta) ({unidad_p})",
                                             min_value=0.0, value=0.5, step=0.5)
            else:
                stk_p = st.number_input(f"Cantidad Inicial en Stock ({unidad_p})",
                                         min_value=0, value=5, step=1)
                stk_min_p = st.number_input(f"Stock Mínimo (Alerta) ({unidad_p})",
                                             min_value=0, value=2, step=1)

            costo_p = st.number_input(f"Costo de Compra ($ por {unidad_p})",
                                       min_value=0.0, step=1000.0)
            venta_p = st.number_input(f"Precio de Venta ($ por {unidad_p})",
                                       min_value=0.0, step=1000.0)

            if costo_p > 0 and venta_p > 0:
                ganancia = venta_p - costo_p
                pct = (ganancia / costo_p) * 100
                color = "🟢" if pct > 0 else "🔴"
                precio_iva = calcular_precio_con_iva(venta_p, iva_tipo_p)
                st.caption(f"{color} Ganancia: {formato_cop(ganancia)} ({pct:.1f}%)")
                if precio_iva != venta_p:
                    st.caption(f"Precio con {iva_tipo_p}: {formato_cop(precio_iva)}")

        if st.form_submit_button("Guardar en Inventario", type="primary"):
            if nom_p and venta_p > 0:
                try:
                    with engine.begin() as conn_ins:
                        conn_ins.execute(text("""
                            INSERT INTO Inventario
                            (usuario_id, nombre_producto, codigo_ref, unidad_medida,
                             stock_actual, stock_minimo, costo_compra, precio_venta, iva_tipo)
                            VALUES (:uid, :nom, :ref, :um, :stk, :stk_min, :costo, :pvp, :iva_tipo)
                        """), {
                            "uid": user_id, "nom": nom_p,
                            "ref": ref_p or None, "um": unidad_p,
                            "stk": float(stk_p), "stk_min": float(stk_min_p),
                            "costo": float(costo_p), "pvp": float(venta_p),
                            "iva_tipo": iva_tipo_p
                        })
                    obtener_metricas_inventario.clear()
                    invalidar_cache_inventario()
                    st.success(f"✅ '{nom_p}' registrado — {formato_cant(stk_p, unidad_p)} en stock a {formato_cop(venta_p)}/{unidad_p} ({iva_tipo_p}).")
                    st.rerun()
                except Exception as e:
                    st.error(mensaje_error_amigable(e, "guardar el producto"))
            else:
                st.warning("Escribe el nombre del producto y asigna un precio de venta válido.")

# ==========================================
# TAB 3: ENTRADAS DE MERCANCÍA CON IA
# ==========================================
with tab_entradas:
    st.subheader("Registrar Entrada de Mercancía")
    st.caption("Sube la factura para que la IA detecte los repuestos, o agrégalos manualmente.")

    gemini_ok = False
    try:
        api_key_gemini = st.secrets["gemini"]["api_key"]
        gemini_ok = True
    except Exception:
        st.warning("⚠️ Gemini no configurado. Agrega `[gemini] api_key = 'tu-key'` en Streamlit Secrets.")

    col_cab1, col_cab2 = st.columns(2)
    with col_cab1:
        factura_img = st.file_uploader(
            "📸 Foto o PDF de la factura del proveedor",
            type=["jpg", "jpeg", "png", "pdf"],
            key="factura_taller"
        )
        if factura_img:
            if factura_img.type != "application/pdf":
                st.image(factura_img, use_container_width=True)
            else:
                st.success(f"📄 {factura_img.name}")

        if factura_img and gemini_ok:
            if st.button("🤖 Analizar Factura con IA", type="primary",
                         use_container_width=True, key="btn_ia_taller"):
                with st.spinner("Gemini está leyendo la factura..."):
                    try:
                        from gemini_utils import leer_factura_imagen, leer_factura_pdf
                        archivo_bytes = factura_img.read()
                        datos = leer_factura_pdf(archivo_bytes) if factura_img.type == "application/pdf" \
                                else leer_factura_imagen(archivo_bytes)
                        if datos and "productos" in datos and datos["productos"]:
                            st.session_state.items_entrada_taller = [
                                {
                                    "nombre": p.get("nombre", ""),
                                    "cantidad": float(p.get("cantidad", 1)),
                                    "costo": float(p.get("costo_unitario", 0)),
                                    "subtotal": float(p.get("subtotal", 0)),
                                }
                                for p in datos["productos"]
                            ]
                            if datos.get("numero_factura"):
                                st.session_state.nf_taller = datos["numero_factura"]
                            st.success(f"✅ IA detectó **{len(datos['productos'])} repuesto(s)**.")
                            st.rerun()
                        else:
                            st.error("No se detectaron productos. Intenta con imagen más clara.")
                    except Exception as e:
                        st.error(mensaje_error_amigable(e, "leer la factura con IA"))

    with col_cab2:
        num_factura = st.text_input("Número de Factura",
                                     value=st.session_state.get("nf_taller", ""),
                                     key="nf_entrada_taller")
        proveedor_txt = st.text_input("Proveedor (opcional)", key="prov_entrada_taller")
        notas_entrada = st.text_area("Notas", height=68, key="notas_entrada_taller")

    st.markdown("---")

    if "items_entrada_taller" not in st.session_state:
        st.session_state.items_entrada_taller = []

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("➕ Agregar repuesto manualmente",
                     use_container_width=True, key="btn_add_taller"):
            st.session_state.items_entrada_taller.append(
                {"nombre": "", "cantidad": 1.0, "costo": 0.0, "subtotal": 0.0}
            )
            st.rerun()
    with col_btn2:
        if st.button("🗑️ Limpiar todo", use_container_width=True, key="btn_clear_taller"):
            st.session_state.confirmar_limpiar_taller = True

    if st.session_state.get("confirmar_limpiar_taller", False):
        st.warning("¿Quitar todos los repuestos de esta entrada? Se perderá lo detectado por la IA y lo agregado manualmente.")
        col_cl1, col_cl2 = st.columns(2)
        with col_cl1:
            if st.button("Sí, limpiar todo", type="primary", use_container_width=True, key="btn_clear_confirm_taller"):
                st.session_state.items_entrada_taller = []
                if "nf_taller" in st.session_state:
                    del st.session_state.nf_taller
                st.session_state.confirmar_limpiar_taller = False
                st.rerun()
        with col_cl2:
            if st.button("Cancelar", use_container_width=True, key="btn_clear_cancel_taller"):
                st.session_state.confirmar_limpiar_taller = False
                st.rerun()

    if not st.session_state.items_entrada_taller:
        st.info("Sube una factura para que la IA detecte los repuestos, o agrega uno manualmente.")
    else:
        df_inv_actual = obtener_inventario_filtrado(user_id, "", LIMITE_FILAS * 10)
        st.markdown(f"**{len(st.session_state.items_entrada_taller)} repuesto(s) en esta entrada:**")

        items_a_eliminar = []
        total_entrada = 0.0

        for i, item in enumerate(st.session_state.items_entrada_taller):
            with st.container(border=True):
                nombre_item = item.get("nombre", "")

                producto_match = None
                if nombre_item and not df_inv_actual.empty:
                    matches = df_inv_actual[
                        df_inv_actual['nombre_producto'].str.lower().str.contains(
                            nombre_item.lower()[:10], na=False
                        )
                    ]
                    if not matches.empty:
                        producto_match = matches.iloc[0]

                col_h1, col_h2 = st.columns([4, 1])
                with col_h1:
                    if producto_match is not None:
                        um = producto_match.get('unidad_medida', 'Unidad')
                        st.success(f"✅ Encontrado: **{producto_match['nombre_producto']}** "
                                   f"(Stock: {formato_cant(producto_match['stock_actual'], um)})")
                    else:
                        st.warning("⚠️ Repuesto nuevo — se creará en el inventario")
                with col_h2:
                    if st.button("❌", key=f"del_t_{i}", help="Quitar este repuesto de la lista"):
                        items_a_eliminar.append(i)

                col_f1, col_f2, col_f3, col_f4 = st.columns([3, 1, 1, 1])
                with col_f1:
                    nom = st.text_input("Nombre del repuesto", value=nombre_item, key=f"nom_t_{i}")
                    st.session_state.items_entrada_taller[i]["nombre"] = nom
                with col_f2:
                    um_actual = producto_match['unidad_medida'] if producto_match is not None \
                                else item.get("unidad_medida", "Unidad")
                    um_sel = st.selectbox("Unidad", UNIDADES,
                                          index=UNIDADES.index(um_actual) if um_actual in UNIDADES else 0,
                                          key=f"um_t_{i}")
                    st.session_state.items_entrada_taller[i]["unidad_medida"] = um_sel
                with col_f3:
                    es_decimal = um_sel in ["kg", "g", "lb", "m", "cm", "vara", "pie",
                                            "L", "mL", "galón", "m²", "m³"]
                    if es_decimal:
                        cant = st.number_input(f"Cant. ({um_sel})", min_value=0.0,
                                               value=float(item.get("cantidad", 1)),
                                               step=0.5, key=f"cant_t_{i}")
                    else:
                        cant = st.number_input(f"Cant. ({um_sel})", min_value=0,
                                               value=int(round(float(item.get("cantidad", 1)))),
                                               step=1, key=f"cant_t_{i}")
                    st.session_state.items_entrada_taller[i]["cantidad"] = float(cant)
                with col_f4:
                    costo = st.number_input(f"Costo/$/{um_sel}", min_value=0.0,
                                            value=float(item.get("costo", 0)),
                                            step=1000.0, key=f"costo_t_{i}")
                    st.session_state.items_entrada_taller[i]["costo"] = costo
                    subtotal_i = cant * costo
                    st.session_state.items_entrada_taller[i]["subtotal"] = subtotal_i
                    st.caption(f"= {formato_cop(subtotal_i)}")

                if producto_match is not None:
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        st.caption(f"PVP actual: {formato_cop(producto_match['precio_venta'])}/{producto_match.get('unidad_medida','Unidad')} · IVA actual: {producto_match.get('iva_tipo') or 'Excluido'}")
                        upd = st.checkbox("Actualizar precio de venta", key=f"upd_t_{i}")
                    with col_e2:
                        pvp = st.number_input("Nuevo PVP ($)", min_value=0.0,
                                              value=float(producto_match['precio_venta']),
                                              step=1000.0, key=f"pvp_t_{i}") if upd \
                              else float(producto_match['precio_venta'])
                    st.session_state.items_entrada_taller[i]["precio_venta"] = pvp
                    st.session_state.items_entrada_taller[i]["producto_id"] = int(producto_match['id'])
                    st.session_state.items_entrada_taller[i]["es_nuevo"] = False
                else:
                    col_n1, col_n2, col_n3 = st.columns(3)
                    with col_n1:
                        pvp_nuevo = st.number_input(f"Precio venta ($/{um_sel}) *",
                                                     min_value=0.0,
                                                     value=float(costo * 1.3) if costo > 0 else 0.0,
                                                     step=1000.0, key=f"pvp_nuevo_t_{i}")
                        st.session_state.items_entrada_taller[i]["precio_venta"] = pvp_nuevo
                    with col_n2:
                        cod_ref = st.text_input("Código / Ref / Barras",
                                                 placeholder="Escanea o escribe",
                                                 key=f"ref_t_{i}")
                        st.session_state.items_entrada_taller[i]["codigo_ref"] = cod_ref
                    with col_n3:
                        iva_nuevo_t = st.selectbox(
                            "Impuesto (IVA)", options=IVA_OPCIONES,
                            index=IVA_OPCIONES.index(IVA_TIPO_DEFAULT),
                            key=f"iva_t_{i}"
                        )
                        st.session_state.items_entrada_taller[i]["iva_tipo"] = iva_nuevo_t
                    st.session_state.items_entrada_taller[i]["es_nuevo"] = True
                    st.session_state.items_entrada_taller[i]["producto_id"] = None

                total_entrada += subtotal_i

        for idx in sorted(items_a_eliminar, reverse=True):
            st.session_state.items_entrada_taller.pop(idx)
        if items_a_eliminar:
            st.rerun()

        if total_entrada > 0:
            st.markdown("---")
            st.info(f"**Total de la entrada: {formato_cop(total_entrada)}**")

        if st.session_state.items_entrada_taller and st.button(
            "✅ Registrar Entrada", type="primary",
            use_container_width=True, key="btn_reg_taller"
        ):
            items_validos = [i for i in st.session_state.items_entrada_taller
                             if i.get("nombre") and i.get("cantidad", 0) > 0]
            if not items_validos:
                st.warning("Agrega al menos un repuesto válido.")
            else:
                try:
                    with engine.begin() as conn:
                        nuevos = actualizados = 0
                        for item in items_validos:
                            pid = item.get("producto_id")
                            pvp = float(item.get("precio_venta", 0))
                            costo = float(item.get("costo", 0))
                            cantidad = float(item.get("cantidad", 1))
                            um = item.get("unidad_medida", "Unidad")
                            cod_ref = item.get("codigo_ref") or None

                            if item.get("es_nuevo") or not pid:
                                iva_tipo_nuevo = item.get("iva_tipo", IVA_TIPO_DEFAULT)
                                conn.execute(text("""
                                    INSERT INTO Inventario
                                    (usuario_id, nombre_producto, codigo_ref, unidad_medida,
                                     stock_actual, stock_minimo, costo_compra, precio_venta, iva_tipo)
                                    VALUES (:uid, :nom, :ref, :um, :stk, 1, :costo, :pvp, :iva_tipo)
                                """), {"uid": user_id, "nom": item["nombre"],
                                       "ref": cod_ref, "um": um,
                                       "stk": cantidad, "costo": costo, "pvp": pvp,
                                       "iva_tipo": iva_tipo_nuevo})
                                nuevos += 1
                            else:
                                conn.execute(text("""
                                    UPDATE Inventario
                                    SET stock_actual = stock_actual + :cant,
                                        costo_compra = :costo, precio_venta = :pvp,
                                        unidad_medida = :um
                                    WHERE id = :pid AND usuario_id = :uid
                                """), {"cant": cantidad, "costo": costo,
                                       "pvp": pvp, "um": um,
                                       "pid": pid, "uid": user_id})
                                actualizados += 1

                    obtener_metricas_inventario.clear()
                    invalidar_cache_inventario()
                    st.session_state.items_entrada_taller = []
                    if "nf_taller" in st.session_state:
                        del st.session_state.nf_taller
                    st.success(f"✅ Entrada registrada: **{nuevos}** nuevo(s), **{actualizados}** actualizado(s).")
                    st.rerun()
                except Exception as e:
                    st.error(mensaje_error_amigable(e, "registrar la entrada de mercancía"))
