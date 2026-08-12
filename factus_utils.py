"""
Módulo para emitir facturas electrónicas a través de la API de Factus.
Cada taller (usuario_id) tiene su propia cuenta de Factus, guardada en
Usuarios.factus_client_id / factus_client_secret / factus_username /
factus_password — no hay credenciales globales.

A diferencia de Alegra, en Factus POST /v2/bills/validate crea Y timbra la
factura ante la DIAN en un solo paso (no hay estado intermedio "abierta"), el
cliente y los ítems van embebidos en cada factura (no hay un recurso
"contacto" persistente que crear antes), y no existe una API de pagos: el
saldo pendiente / abonos de una orden a crédito se maneja 100% dentro de
MyTaller (ver queries.registrar_abono), sin sincronizar nada con Factus.
"""

import base64
from datetime import date
import requests
import streamlit as st
from db import mensaje_error_amigable

BASE_URL_SANDBOX = "https://api-sandbox.factus.com.co"
BASE_URL_PRODUCCION = "https://api.factus.com.co"
# Mientras no haya talleres facturando en vivo, todo apunta al sandbox
# (gratis e ilimitado, espejo exacto de producción). Cambiar a
# BASE_URL_PRODUCCION cuando un taller tenga credenciales reales de Factus.
BASE_URL = BASE_URL_SANDBOX

# --- Catálogos DIAN usados al armar el payload (ver Tablas de referencia de Factus) ---
TIPO_DOC_FACTUS = {"NIT": "31", "CC": "13"}
ORGANIZACION_FACTUS = {"NIT": "1", "CC": "2"}  # 1=Persona jurídica, 2=Persona natural
RESPONSABILIDADES_FACTUS = {
    "COMMON_REGIME": ["O-23"],      # Agente de retención de IVA / responsable de IVA
    "SIMPLIFIED_REGIME": ["R-99-PN"],  # No responsable
}
UNIDAD_MEDIDA_DEFECTO = "94"  # "unidad" — MyTaller no distingue unidades finas
CODIGO_IMPUESTO_IVA = "01"
PAYMENT_FORM_FACTUS = {"Efectivo": "1", "Transferencia": "1", "Mixto": "1", "Credito": "2"}
PAYMENT_METHOD_FACTUS = {"Efectivo": "10", "Transferencia": "47", "Mixto": "10"}


def _obtener_token(client_id, client_secret, username, password):
    """Pide un access_token nuevo (dura 1h en Factus). No se cachea entre
    reruns de Streamlit: el volumen de un taller no justifica la complejidad
    de manejar refresh_token, y pedir uno nuevo por operación es gratis."""
    resp = requests.post(
        f"{BASE_URL}/oauth/token",
        headers={"Accept": "application/json"},
        data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return None, _mensaje_error(resp)
    return resp.json().get("access_token"), None


def _mensaje_error(resp):
    """Extrae el mensaje legible de una respuesta de error de Factus (suele
    devolver JSON tipo {"message": "...", "errors": {...}}); si no se puede
    parsear, cae al texto crudo para no ocultar información."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            partes = [str(data[k]) for k in ("message", "error", "error_description") if data.get(k)]
            if data.get("errors"):
                partes.append(str(data["errors"]))
            if partes:
                return " — ".join(partes)
    except ValueError:
        pass
    return resp.text


def probar_conexion(client_id, client_secret, username, password):
    """Verifica que unas credenciales de Factus funcionen, pidiendo un token."""
    try:
        token, error = _obtener_token(client_id, client_secret, username, password)
        if token:
            return True, "Conexión exitosa."
        return False, f"Credenciales rechazadas: {error}"
    except requests.RequestException as e:
        return False, f"Error de conexión: {e}"


def listar_rangos_numeracion(client_id, client_secret, username, password):
    """Diagnóstico: consulta los rangos de numeración (autorización DIAN) que
    tiene activos esta cuenta de Factus. Sin un rango activo, /v2/bills/validate
    rechaza cualquier factura con un 422 genérico sin detalle de campo."""
    try:
        token, error = _obtener_token(client_id, client_secret, username, password)
        if not token:
            return False, f"No se pudo autenticar con Factus: {error}"
        resp = requests.get(f"{BASE_URL}/v2/numbering-ranges", headers=_headers(token), timeout=15)
        if resp.status_code not in (200, 201):
            return False, f"Error consultando rangos ({resp.status_code}): {_mensaje_error(resp)}"
        return True, resp.json()
    except requests.RequestException as e:
        return False, f"Error de conexión: {e}"


def obtener_credenciales(uid):
    """Devuelve (client_id, client_secret, username, password) configurados
    por este taller, o (None, None, None, None) si no ha configurado nada."""
    import queries

    taller = queries.obtener_credenciales_factus(uid)
    if not taller or not taller.factus_client_id or not taller.factus_client_secret:
        return None, None, None, None
    return taller.factus_client_id, taller.factus_client_secret, taller.factus_username, taller.factus_password


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}


def _construir_customer(empresa):
    """Arma el objeto 'customer' embebido en la factura/nota crédito a partir
    de una Empresa_Cliente de MyTaller."""
    tipo_doc = empresa.tipo_documento or "NIT"
    customer = {
        "identification_document_code": TIPO_DOC_FACTUS.get(tipo_doc, "31"),
        "identification": empresa.nit,
        "legal_organization_code": ORGANIZACION_FACTUS.get(tipo_doc, "1"),
        "tribute_code": "ZZ",
        "responsibilities": RESPONSABILIDADES_FACTUS.get(empresa.regimen, ["R-99-PN"]),
        "country_code": "CO",
    }
    if tipo_doc == "NIT":
        customer["company"] = empresa.razon_social
        if empresa.digito_verificacion:
            customer["dv"] = str(empresa.digito_verificacion)
    else:
        customer["names"] = empresa.razon_social
    if empresa.email:
        customer["email"] = empresa.email
    return customer


def _construir_item(descripcion, precio_venta, iva_porcentaje, codigo_ref):
    """Arma un renglón de la factura/nota crédito a partir de un ítem de
    MyTaller (mano de obra o repuesto)."""
    iva_porcentaje = float(iva_porcentaje or 0)
    item = {
        "code_reference": codigo_ref,
        "name": descripcion[:250],
        "quantity": "1.00",
        "discount_rate": "0.00",
        "price": f"{float(precio_venta):.2f}",
        "unit_measure_code": UNIDAD_MEDIDA_DEFECTO,
        "standard_code": "999",
    }
    if iva_porcentaje > 0:
        item["taxes"] = [{"code": CODIGO_IMPUESTO_IVA, "rate": f"{iva_porcentaje:.2f}"}]
    else:
        item["taxes"] = [{"code": CODIGO_IMPUESTO_IVA, "rate": "0.00", "is_excluded": True}]
    return item


def _construir_payment_details(tipo_pago, total, fecha_vencimiento=None):
    forma = PAYMENT_FORM_FACTUS.get(tipo_pago, "1")
    detalle = {
        "payment_form": forma,
        "payment_method_code": PAYMENT_METHOD_FACTUS.get(tipo_pago, "1") if forma == "1" else "1",
        "amount": f"{float(total):.2f}",
    }
    if forma == "2" and fecha_vencimiento:
        detalle["due_date"] = fecha_vencimiento.isoformat() if hasattr(fecha_vencimiento, "isoformat") else str(fecha_vencimiento)
    return [detalle]


def _pdf_base64_a_data_url(pdf_base64):
    """Factus ya entrega el PDF/XML codificados en base64 directo (no un
    enlace temporal como Alegra) — se guardan tal cual como enlace propio,
    sin necesidad de descargarlos de ningún lado."""
    if not pdf_base64:
        return None
    return f"data:application/pdf;base64,{pdf_base64}"


def _xml_base64_a_data_url(xml_base64):
    if not xml_base64:
        return None
    return f"data:application/xml;base64,{xml_base64}"


def _descargar_pdf(token, numero_factura):
    try:
        resp = requests.get(f"{BASE_URL}/v2/bills/{numero_factura}/download-pdf", headers=_headers(token), timeout=20)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("pdf_base_64_encoded")
    except requests.RequestException:
        pass
    return None


def _descargar_xml(token, numero_factura):
    try:
        resp = requests.get(f"{BASE_URL}/v2/bills/{numero_factura}/download-xml", headers=_headers(token), timeout=20)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("xml_base_64_encoded")
    except requests.RequestException:
        pass
    return None


def facturar_orden(uid, hoja_id, tipo_pago, fecha_vencimiento=None, notas=None, orden_compra=None):
    """
    Crea Y timbra ante la DIAN la factura electrónica de una orden ya
    registrada en MyTaller, usando la cuenta de Factus propia del taller
    'uid'. A diferencia de Alegra, esto ocurre en un solo paso — no queda
    'abierta' pendiente de emitir por separado.
    notas: se envía como 'observation' de la factura (aparece en el PDF).
    orden_compra: no tiene campo directo en Factus; se antepone a la
    observación si se indica.
    Devuelve (True, mensaje) o (False, mensaje).
    """
    import queries
    from pdf_utils import IVA_TASA, resolver_iva_tipo, calcular_totales_orden
    import pandas as pd

    client_id, client_secret, username, password = obtener_credenciales(uid)
    if not client_id:
        return False, "Este taller no tiene configurada su cuenta de facturación electrónica. Ve a Configuración del Taller → Facturación Electrónica."

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return False, "Orden no encontrada."
    if orden.factura_reference_code:
        return False, "Esta orden ya tiene una factura creada."

    empresa = queries.obtener_datos_facturacion_empresa(uid, orden.empresa_id)
    if not empresa:
        return False, "Cliente no encontrado."

    renglones = queries.obtener_items_orden(hoja_id)
    if not renglones:
        return False, "Esta orden no tiene ítems para facturar."

    config = queries.obtener_config_taller(uid)
    iva_activo = bool(config[4]) if config and config[4] is not None else False
    iva_incluido = bool(config[5]) if config and config[5] is not None else False
    iva_tipo_default_mo = config[6] if config and config[6] else "Excluido"
    iva_tipo_default_rep = config[7] if config and config[7] else "Excluido"

    items_payload = []
    for i, r in enumerate(renglones, start=1):
        etiqueta = resolver_iva_tipo(r.iva_tipo)
        if etiqueta is None:
            etiqueta = iva_tipo_default_mo if r.tipo_item == "Mano de Obra" else iva_tipo_default_rep
        if not iva_activo:
            etiqueta = "Excluido"
        iva_porcentaje = IVA_TASA.get(etiqueta, 0.0)

        precio_venta = float(r.precio_venta or 0)
        if iva_incluido and iva_porcentaje > 0:
            precio_base = precio_venta / (1 + iva_porcentaje / 100)
        else:
            precio_base = precio_venta

        items_payload.append(_construir_item(r.descripcion, precio_base, iva_porcentaje, f"ITEM-{hoja_id}-{i}"))

    df_renglones = pd.DataFrame([
        {"precio_venta": r.precio_venta, "tipo_item": r.tipo_item, "iva_tipo": r.iva_tipo} for r in renglones
    ])
    _, _, gran_total, _ = calcular_totales_orden(
        df_renglones, iva_activo=iva_activo, iva_incluido=iva_incluido,
        iva_tipo_default_mano_obra=iva_tipo_default_mo, iva_tipo_default_repuestos=iva_tipo_default_rep
    )

    observacion = notas or ""
    if orden_compra:
        observacion = f"OC: {orden_compra}. {observacion}".strip()

    payload = {
        "reference_code": f"MYT-{uid}-{hoja_id}",
        "document": "01",
        "payment_details": _construir_payment_details(tipo_pago, gran_total, fecha_vencimiento),
        "customer": _construir_customer(empresa),
        "items": items_payload,
    }
    if observacion:
        payload["observation"] = observacion[:250]

    try:
        token, error = _obtener_token(client_id, client_secret, username, password)
        if not token:
            return False, f"No se pudo autenticar con Factus: {error}"

        resp = requests.post(f"{BASE_URL}/v2/bills/validate", headers=_headers(token), json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            return False, f"La factura fue rechazada ({resp.status_code}): {_mensaje_error(resp)}"

        data = resp.json().get("data", {})
        bill = data.get("bill", data)
        numero_factura = bill.get("number") or bill.get("bill_number")
        cufe = bill.get("cufe") or (bill.get("legal_stamp") or {}).get("cufe")
        is_validated = bill.get("is_validated", True)

        if not is_validated:
            return False, (
                "La factura se creó pero la DIAN no la validó todavía. Revisa el estado en Factus "
                "e inténtalo de nuevo (usa 'Eliminar no validada' desde Factus si necesitas reintentar)."
            )

        pdf_url = _pdf_base64_a_data_url(_descargar_pdf(token, numero_factura)) if numero_factura else None
        xml_url = _xml_base64_a_data_url(_descargar_xml(token, numero_factura)) if numero_factura else None

        saldo_pendiente = gran_total if tipo_pago == "Credito" else None

        queries.guardar_resultado_factura(
            hoja_id,
            reference_code=payload["reference_code"],
            cufe=cufe,
            pdf_url=pdf_url,
            xml_url=xml_url,
            estado="emitida",
            prefijo=None,
            numero=numero_factura,
            tipo_pago=tipo_pago,
            fecha_vencimiento=fecha_vencimiento,
            saldo_pendiente=saldo_pendiente,
        )
        queries.marcar_orden_facturada(hoja_id)

        return True, f"Factura {numero_factura} emitida ante la DIAN."
    except requests.RequestException as e:
        return False, mensaje_error_amigable(e, "conectar con Factus para crear la factura")


def anular_factura_orden(uid, hoja_id):
    """
    Emite la nota crédito en Factus que anula la factura electrónica de una
    orden (cuando el trabajo se anula/devuelve después de facturado). No hace
    nada (y no es un error) si la orden nunca tuvo factura electrónica emitida.
    Devuelve (True, mensaje) o (False, mensaje).
    """
    import queries
    from pdf_utils import IVA_TASA, resolver_iva_tipo

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return False, "Orden no encontrada."
    if orden.factura_estado != "emitida" or not orden.factura_numero:
        return True, "Esta orden no tenía factura electrónica emitida, no se requiere nota crédito."
    if orden.nota_credito_reference_code:
        return False, "Esta orden ya tiene una nota crédito emitida."

    client_id, client_secret, username, password = obtener_credenciales(uid)
    if not client_id:
        return False, "Este taller no tiene configurada su cuenta de facturación electrónica."

    empresa = queries.obtener_datos_facturacion_empresa(uid, orden.empresa_id)
    if not empresa:
        return False, "No se pudo obtener el cliente."

    renglones = queries.obtener_items_orden(hoja_id)
    if not renglones:
        return False, "No hay ítems para la nota crédito."

    config = queries.obtener_config_taller(uid)
    iva_activo = bool(config[4]) if config and config[4] is not None else False
    iva_incluido = bool(config[5]) if config and config[5] is not None else False
    iva_tipo_default_mo = config[6] if config and config[6] else "Excluido"
    iva_tipo_default_rep = config[7] if config and config[7] else "Excluido"

    items_payload = []
    total_orden = 0.0
    for i, r in enumerate(renglones, start=1):
        etiqueta = resolver_iva_tipo(r.iva_tipo)
        if etiqueta is None:
            etiqueta = iva_tipo_default_mo if r.tipo_item == "Mano de Obra" else iva_tipo_default_rep
        if not iva_activo:
            etiqueta = "Excluido"
        iva_porcentaje = IVA_TASA.get(etiqueta, 0.0)

        precio_venta = float(r.precio_venta or 0)
        if iva_incluido and iva_porcentaje > 0:
            precio_base = precio_venta / (1 + iva_porcentaje / 100)
        else:
            precio_base = precio_venta

        items_payload.append(_construir_item(r.descripcion, precio_base, iva_porcentaje, f"ITEM-{hoja_id}-{i}"))
        total_orden += precio_base

    reference_code_nc = f"MYT-NC-{uid}-{hoja_id}"
    payload = {
        "reference_code": reference_code_nc,
        "correction_concept_code": "2",  # Anulación de factura electrónica
        "bill_number": orden.factura_numero,
        "payment_details": _construir_payment_details(orden.tipo_pago or "Efectivo", total_orden),
        "customer": _construir_customer(empresa),
        "items": items_payload,
    }

    try:
        token, error = _obtener_token(client_id, client_secret, username, password)
        if not token:
            return False, f"No se pudo autenticar con Factus: {error}"

        resp = requests.post(f"{BASE_URL}/v2/credit-notes/validate", headers=_headers(token), json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            return False, f"La nota crédito fue rechazada ({resp.status_code}): {_mensaje_error(resp)}"

        data = resp.json().get("data", {})
        nota = data.get("credit_note", data)
        numero_nc = nota.get("number")

        pdf_url_nc = _pdf_base64_a_data_url(_descargar_pdf_nota_credito(token, numero_nc)) if numero_nc else None
        xml_url_nc = _xml_base64_a_data_url(_descargar_xml_nota_credito(token, numero_nc)) if numero_nc else None

        queries.guardar_nota_credito(
            hoja_id, reference_code_nc, pdf_url=pdf_url_nc, xml_url=xml_url_nc,
            prefijo=None, numero=numero_nc,
        )
        return True, f"Nota crédito emitida ({numero_nc})."
    except requests.RequestException as e:
        return False, mensaje_error_amigable(e, "conectar con Factus para crear la nota crédito")


def _descargar_pdf_nota_credito(token, numero_nc):
    try:
        resp = requests.get(f"{BASE_URL}/v2/credit-notes/{numero_nc}/download-pdf", headers=_headers(token), timeout=20)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("pdf_base_64_encoded")
    except requests.RequestException:
        pass
    return None


def _descargar_xml_nota_credito(token, numero_nc):
    try:
        resp = requests.get(f"{BASE_URL}/v2/credit-notes/{numero_nc}/download-xml", headers=_headers(token), timeout=20)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("xml_base_64_encoded")
    except requests.RequestException:
        pass
    return None


def refrescar_url_factura_orden(uid, hoja_id):
    """
    Devuelve (pdf_url, xml_url) de la factura de esta orden. A diferencia de
    Alegra, Factus no da enlaces temporales — lo que se guardó al facturar ES
    la copia permanente, así que esto solo lee lo ya guardado (sin llamar a
    la API de nuevo).
    """
    import queries

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return None, None
    return orden.factura_pdf_url, orden.factura_xml_url


def refrescar_url_nota_credito_orden(uid, hoja_id):
    """Igual que refrescar_url_factura_orden(), pero para la nota crédito."""
    import queries

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return None, None
    return orden.nota_credito_pdf_url, orden.nota_credito_xml_url


def _es_copia_propia(url):
    """True si el enlace ya contiene el archivo adentro (data:...;base64,...).
    isinstance(url, str) primero: un valor vacío proveniente de un DataFrame
    de pandas llega como NaN (float), no None."""
    return isinstance(url, str) and url.startswith("data:")


def _bytes_desde_enlace_propio(url):
    if not _es_copia_propia(url):
        return None
    try:
        _, b64data = url.split(",", 1)
        return base64.b64decode(b64data)
    except Exception:
        return None


def mostrar_documento(contenedor, etiqueta, url, nombre_archivo, mime_type):
    """
    Muestra un botón para abrir/descargar un PDF o XML de una factura o nota
    crédito. Factus siempre entrega el documento como copia propia (data:),
    así que se usa st.download_button con los bytes decodificados: varios
    navegadores (Chrome incluido) bloquean abrir un enlace data: en una
    pestaña nueva.
    contenedor: st, o una columna devuelta por st.columns().
    """
    if not isinstance(url, str) or not url:
        return
    contenido = _bytes_desde_enlace_propio(url)
    if contenido:
        contenedor.download_button(
            etiqueta, data=contenido, file_name=nombre_archivo,
            mime=mime_type, width='stretch',
        )
    else:
        contenedor.link_button(etiqueta, url, width='stretch')
