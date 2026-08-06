"""
Módulo para emitir facturas electrónicas a través de la API de Alegra.
Cada taller (usuario_id) tiene su propia cuenta de Alegra, guardada en
Usuarios.alegra_email / Usuarios.alegra_token — no hay credenciales globales.
"""

import base64
from datetime import date
import requests
import streamlit as st

BASE_URL = "https://api.alegra.com/api/v1"


def _headers(email, token):
    """Arma el header Authorization Basic a partir de las credenciales dadas."""
    credenciales = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {credenciales}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _mensaje_error(resp):
    """Extrae el mensaje legible de una respuesta de error de la API (el
    proveedor devuelve JSON tipo {"message": "...", "code": N}); si no se
    puede parsear, cae al texto crudo para no ocultar información."""
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
    except ValueError:
        pass
    return resp.text


def _descargar_bytes(url):
    """Descarga el contenido de un enlace de Alegra (el PDF o el XML) para
    guardar una copia propia. Ese enlace vence a los pocos minutos u horas -
    esta es la única oportunidad de traer el archivo mientras todavía sirve."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.content
        return None
    except requests.RequestException:
        return None


def _guardar_como_enlace_propio(url, tipo_mime):
    """Convierte un enlace temporal de Alegra en uno que contiene el archivo
    completo adentro (no un link a Alegra, sino el documento mismo, codificado).
    Ese enlace nunca vence porque no depende de que Alegra lo siga teniendo.
    Si no se pudo descargar, devuelve el enlace original tal cual (sigue
    sirviendo mientras esté vigente)."""
    contenido = _descargar_bytes(url)
    if not contenido:
        return url
    return f"data:{tipo_mime};base64,{base64.b64encode(contenido).decode()}"


def probar_conexion(email, token):
    """Verifica que un par email/token funcione contra la API de Alegra."""
    try:
        resp = requests.get(f"{BASE_URL}/contacts", headers=_headers(email, token), params={"limit": 1}, timeout=15)
        if resp.status_code == 200:
            return True, "Conexión exitosa."
        if resp.status_code == 401:
            return False, "Credenciales rechazadas (email o token incorrectos)."
        return False, f"El proveedor respondió {resp.status_code}: {_mensaje_error(resp)}"
    except requests.RequestException as e:
        return False, f"Error de conexión: {e}"


def crear_contacto(email, token, nombre, identificacion, tipo_identificacion="NIT", email_cliente=None,
                    kind_of_person="BUSINESS_ENTITY", regimen="SIMPLIFIED_REGIME"):
    """
    Crea un contacto/cliente en Alegra y devuelve su id, o None si falla.
    kind_of_person: 'PERSON_ENTITY' (persona natural) o 'BUSINESS_ENTITY' (empresa/NIT).
    regimen: 'SIMPLIFIED_REGIME' (régimen simplificado) o 'COMMON_REGIME' (régimen común).
    """
    partes = nombre.strip().split(" ", 1)
    first_name = partes[0]
    last_name = partes[1] if len(partes) > 1 else ""

    payload = {
        "name": nombre,
        "nameObject": {"firstName": first_name, "lastName": last_name},
        "identification": identificacion,
        "type": "client",
        "kindOfPerson": kind_of_person,
        "regime": regimen,
        "identificationObject": {"type": tipo_identificacion, "number": identificacion},
    }
    if email_cliente:
        payload["email"] = email_cliente

    try:
        resp = requests.post(f"{BASE_URL}/contacts", headers=_headers(email, token), json=payload, timeout=15)
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        st.error(f"Error al crear contacto ({resp.status_code}): {_mensaje_error(resp)}")
        return None
    except requests.RequestException as e:
        st.error(f"Error de conexión al crear contacto: {e}")
        return None


# Unidad de medida de MyTaller -> catálogo de Alegra/DIAN. Es obligatoria para
# poder timbrar la factura electrónica ante la DIAN ("el campo unidad de
# medida es requerido"); sin esto Alegra crea la factura pero nunca la emite.
UNIDAD_MEDIDA_ALEGRA = {
    "Unidad": "unit",
    "kg": "kilogram",
    "g": "gram",
    "m": "meter",
    "cm": "centimeter",
    "L": "liter",
    "mL": "mililiter",
    "galón": "gallon",
    "Caja": "box",
    "m²": "meterSquared",
    "m³": "cubicMeter",
}


def crear_item_ad_hoc(email, token, nombre, precio, unidad_medida="Unidad"):
    """
    Crea un ítem/servicio en el catálogo de Alegra para un renglón puntual de
    una orden (mano de obra o repuesto). No se guarda ni se reutiliza el id:
    la descripción de cada renglón suele ser específica de ese trabajo
    (ej. "Cambio de pastillas delanteras - Toyota Corolla placa ABC123"),
    así que se crea un ítem nuevo cada vez que se factura una orden.
    Devuelve el id del ítem creado, o None si falla.
    """
    payload = {
        "name": nombre[:250],
        "price": precio,
        "inventory": {"unit": UNIDAD_MEDIDA_ALEGRA.get(unidad_medida, "unit")},
    }
    try:
        resp = requests.post(f"{BASE_URL}/items", headers=_headers(email, token), json=payload, timeout=15)
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        st.error(f"Error al crear ítem '{nombre}' ({resp.status_code}): {_mensaje_error(resp)}")
        return None
    except requests.RequestException as e:
        st.error(f"Error de conexión al crear ítem: {e}")
        return None


def crear_factura_orden(email, token, cliente_id, items, due_date=None,
                         payment_form=None, payment_method=None):
    """
    Crea una factura de venta en Alegra a partir de una orden de MyTaller.
    items: lista de dicts [{"id": <id_item_alegra>, "price": float, "quantity": 1}, ...]
    due_date: fecha límite de pago (str yyyy-mm-dd). Si es None, se usa hoy (pago de contado).
    payment_form: 'CASH' o 'CREDIT' - obligatorio para facturación electrónica 2.1 en Colombia.
    payment_method: medio de pago (ej. 'CASH', 'DEBIT_TRANSFER_BANK') - obligatorio cuando
    payment_form es 'CASH' con facturación electrónica 2.1 activa.
    No se envía 'stamp' (timbrado): la factura queda 'abierta' en Alegra con su
    número asignado pero sin CUFE, hasta que se llame a emitir_factura_dian()
    para emitirla ante la DIAN cuando el taller lo decida.
    Devuelve el JSON de la factura creada (incluye pdf) o None si falla.
    """
    payload = {
        "date": date.today().isoformat(),
        "dueDate": due_date or date.today().isoformat(),
        "client": {"id": cliente_id},
        "items": items,
        "status": "open",
    }
    if payment_form == "CREDIT":
        payload["periodicity"] = "MANUAL"
    if payment_form:
        payload["paymentForm"] = payment_form
    if payment_method:
        payload["paymentMethod"] = payment_method

    try:
        resp = requests.post(f"{BASE_URL}/invoices", headers=_headers(email, token), json=payload, timeout=30)
        if resp.status_code in (200, 201):
            return resp.json()
        st.error(f"Error al crear factura ({resp.status_code}): {_mensaje_error(resp)}")
        return None
    except requests.RequestException as e:
        st.error(f"Error de conexión al crear factura: {e}")
        return None


def emitir_factura_dian(email, token, factura_id):
    """
    Timbra ante la DIAN una factura que ya existe en Alegra en estado 'abierta'.
    Devuelve (True, mensaje) o (False, mensaje).
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/invoices/stamp",
            headers=_headers(email, token),
            json={"ids": [int(factura_id)]},
            timeout=30,
        )
    except requests.RequestException as e:
        return False, f"Error de conexión al timbrar: {e}"

    if resp.status_code not in (200, 201):
        return False, f"El timbrado fue rechazado ({resp.status_code}): {_mensaje_error(resp)}"

    try:
        resultados = resp.json().get("data", [])
    except ValueError:
        return False, "Se recibió una respuesta inesperada al timbrar."

    resultado = next((r for r in resultados if str(r.get("id")) == str(factura_id)), None)
    if not resultado or not resultado.get("success"):
        msg = resultado.get("message") if resultado else "No se confirmó el timbrado."
        return False, msg

    return True, resultado.get("message", "Factura emitida ante la DIAN.")


def obtener_factura(email, token, factura_id):
    """Consulta el estado actual de una factura en Alegra, pidiendo explícitamente
    el PDF y el XML timbrado (el documento legal ante la DIAN): Alegra no los
    incluye por defecto, hay que pedirlos con ?fields=pdf,xml."""
    try:
        resp = requests.get(
            f"{BASE_URL}/invoices/{factura_id}", headers=_headers(email, token),
            params={"fields": "pdf,xml"}, timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def obtener_nota_credito(email, token, nota_id):
    """Consulta el estado actual de una nota crédito en Alegra, pidiendo explícitamente
    el PDF y el XML timbrado (igual que las facturas, Alegra no los incluye por defecto)."""
    try:
        resp = requests.get(
            f"{BASE_URL}/credit-notes/{nota_id}", headers=_headers(email, token),
            params={"fields": "pdf,xml"}, timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def crear_nota_credito(email, token, factura_alegra_id, cliente_id, items, total):
    """
    Crea una nota crédito en Alegra que anula (total o parcialmente) una
    factura ya emitida. Devuelve el JSON de la nota crédito creada, o None si falla.
    """
    payload = {
        "date": date.today().isoformat(),
        "client": {"id": cliente_id},
        "items": items,
        # 'invoiceCreditAllocations' es el campo específico de Colombia para
        # ligar la nota crédito a la factura electrónica que anula (necesario
        # para que quede asociada ante la DIAN, no solo como nota suelta).
        "invoiceCreditAllocations": [{"id": factura_alegra_id, "amount": float(total)}],
        "type": "VOID_ELECTRONIC_INVOICE",
        # Igual que en la factura: sin esto Alegra crea la nota crédito pero
        # nunca la emite ante la DIAN.
        "stamp": {"generateStamp": True},
    }

    try:
        resp = requests.post(f"{BASE_URL}/credit-notes", headers=_headers(email, token), json=payload, timeout=30)
        if resp.status_code in (200, 201):
            return resp.json()
        st.error(f"Error al crear nota crédito ({resp.status_code}): {_mensaje_error(resp)}")
        return None
    except requests.RequestException as e:
        st.error(f"Error de conexión al crear nota crédito: {e}")
        return None


@st.cache_data(ttl=3600)
def obtener_impuesto_por_porcentaje(email, token, porcentaje):
    """
    Busca en el catálogo de impuestos de la cuenta de Alegra el id del IVA
    que coincida con ese porcentaje (ej. 19 -> id del 'IVA 19%'). Las cuentas
    colombianas de Alegra ya traen el catálogo estándar de IVA por defecto.
    Devuelve None si no encuentra uno que coincida.
    """
    try:
        resp = requests.get(f"{BASE_URL}/taxes", headers=_headers(email, token), params={"limit": 30}, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        impuestos = data.get("results", []) if isinstance(data, dict) else data
        for imp in impuestos:
            if imp.get("type") == "IVA" and abs(float(imp.get("percentage", -1)) - float(porcentaje)) < 0.01:
                return imp.get("id")
        return None
    except (requests.RequestException, ValueError, TypeError):
        return None


def _construir_item_payload(item_id, precio_venta, iva_porcentaje, iva_incluido, email, token):
    """
    Arma el renglón de factura para Alegra a partir de un ítem de MyTaller:
    calcula el precio base sin IVA (según si el taller cobra el IVA aparte o
    ya incluido en el precio) y referencia el impuesto correspondiente. Cada
    renglón de MyTaller es un ítem único (sin cantidad ni descuento propios:
    la cantidad, si aplica, ya viene multiplicada dentro del precio total).
    """
    iva_porcentaje = float(iva_porcentaje or 0)
    precio_venta = float(precio_venta or 0)

    if iva_incluido and iva_porcentaje > 0:
        precio_base = precio_venta / (1 + iva_porcentaje / 100)
    else:
        precio_base = precio_venta

    payload = {
        "id": item_id,
        "price": round(precio_base, 2),
        "quantity": 1,
    }

    if iva_porcentaje > 0:
        tax_id = obtener_impuesto_por_porcentaje(email, token, iva_porcentaje)
        if tax_id:
            payload["tax"] = [{"id": tax_id}]

    return payload


def obtener_credenciales(uid):
    """Devuelve (email, token) de Alegra configurados por este taller, o (None, None) si no ha configurado nada."""
    import queries

    taller = queries.obtener_credenciales_alegra(uid)
    if not taller or not taller.alegra_email or not taller.alegra_token:
        return None, None
    return taller.alegra_email, taller.alegra_token


def obtener_o_crear_contacto_empresa(uid, empresa_id, email, token):
    """
    Devuelve el alegra_contact_id de una Empresa_Cliente de MyTaller, creándolo
    en Alegra (con la cuenta del taller 'uid') la primera vez si todavía no existe.
    """
    import queries

    empresa = queries.obtener_datos_facturacion_empresa(uid, empresa_id)
    if not empresa:
        st.error("Cliente no encontrado.")
        return None

    if empresa.alegra_contact_id:
        return empresa.alegra_contact_id

    tipo_doc = empresa.tipo_documento or "NIT"
    alegra_id = crear_contacto(
        email, token,
        nombre=empresa.razon_social,
        identificacion=empresa.nit,
        tipo_identificacion=tipo_doc,
        email_cliente=empresa.email,
        kind_of_person="BUSINESS_ENTITY" if tipo_doc == "NIT" else "PERSON_ENTITY",
    )
    if alegra_id:
        queries.guardar_alegra_contact_id(empresa_id, alegra_id)
    return alegra_id


# Método de pago de MyTaller -> catálogo de Alegra (obligatorio en Colombia
# para facturación electrónica 2.1). paymentMethod solo aplica cuando
# paymentForm es 'CASH'; en 'CREDIT' Alegra no lo exige.
PAYMENT_METHOD_ALEGRA = {
    "Efectivo": "CASH",
    "Transferencia": "DEBIT_TRANSFER_BANK",
    "Mixto": "CASH",
}


def _forma_y_medio_pago(tipo_pago):
    """Traduce el método de pago elegido al facturar a (paymentForm, paymentMethod) de Alegra."""
    if tipo_pago == "Credito":
        return "CREDIT", None
    return "CASH", PAYMENT_METHOD_ALEGRA.get(tipo_pago, "CASH")


def facturar_orden(uid, hoja_id, tipo_pago, fecha_vencimiento=None):
    """
    Crea en Alegra la factura electrónica de una orden ya registrada en
    MyTaller, usando la cuenta de Alegra propia del taller 'uid': crea (o
    reutiliza) el cliente, crea un ítem por cada renglón de la orden y arma
    la factura.
    La factura queda 'abierta' (con su número asignado) pero SIN timbrar ante
    la DIAN todavía - eso requiere un paso aparte (emitir_factura_dian_orden),
    para que el taller pueda revisarla antes de emitirla oficialmente.
    Devuelve (True, mensaje) o (False, mensaje).
    """
    import queries

    email, token = obtener_credenciales(uid)
    if not email or not token:
        return False, "Este taller no tiene configurada su cuenta de facturación electrónica. Ve a Configuración del Taller → Facturación Electrónica."

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return False, "Orden no encontrada."
    if orden.factura_alegra_id:
        return False, "Esta orden ya tiene una factura creada."

    contacto_id = obtener_o_crear_contacto_empresa(uid, orden.empresa_id, email, token)
    if not contacto_id:
        return False, "No se pudo crear/obtener el cliente en Alegra."

    renglones = queries.obtener_items_orden(hoja_id)
    if not renglones:
        return False, "Esta orden no tiene ítems para facturar."

    config = queries.obtener_config_taller(uid)
    iva_activo = bool(config[4]) if config and config[4] is not None else False
    iva_incluido = bool(config[5]) if config and config[5] is not None else False
    iva_tipo_default_mo = config[6] if config and config[6] else "Excluido"
    iva_tipo_default_rep = config[7] if config and config[7] else "Excluido"

    from pdf_utils import IVA_TASA, resolver_iva_tipo

    items_payload = []
    for r in renglones:
        etiqueta = resolver_iva_tipo(r.iva_tipo)
        if etiqueta is None:
            etiqueta = iva_tipo_default_mo if r.tipo_item == "Mano de Obra" else iva_tipo_default_rep
        if not iva_activo:
            etiqueta = "Excluido"
        iva_porcentaje = IVA_TASA.get(etiqueta, 0.0)

        item_id = crear_item_ad_hoc(email, token, r.descripcion, float(r.precio_venta))
        if not item_id:
            return False, f"No se pudo crear el ítem '{r.descripcion}' en Alegra."
        items_payload.append(_construir_item_payload(item_id, r.precio_venta, iva_porcentaje, iva_incluido, email, token))

    payment_form, payment_method = _forma_y_medio_pago(tipo_pago)
    due_date = fecha_vencimiento.isoformat() if fecha_vencimiento else None

    factura = crear_factura_orden(
        email, token, contacto_id, items_payload, due_date=due_date,
        payment_form=payment_form, payment_method=payment_method,
    )
    if not factura:
        return False, "La factura fue rechazada. Revisa el error mostrado arriba."

    number_template = factura.get("numberTemplate") if isinstance(factura.get("numberTemplate"), dict) else {}
    pdf_url = factura.get("pdf") if isinstance(factura.get("pdf"), str) else None
    if not pdf_url:
        factura_completa = obtener_factura(email, token, factura.get("id"))
        if factura_completa:
            pdf_url = factura_completa.get("pdf") if isinstance(factura_completa.get("pdf"), str) else None

    # Copia propia del PDF (no solo el enlace de Alegra, que vence a los
    # pocos minutos u horas) para que "Abrir" funcione siempre.
    pdf_url = _guardar_como_enlace_propio(pdf_url, "application/pdf")

    queries.guardar_resultado_factura(
        hoja_id,
        alegra_id=factura.get("id"),
        pdf_url=pdf_url,
        estado="abierta",
        prefijo=number_template.get("prefix"),
        numero=str(number_template["number"]) if number_template.get("number") is not None else None,
        tipo_pago=tipo_pago,
        fecha_vencimiento=fecha_vencimiento,
    )

    numero_texto = f"{number_template.get('prefix') or ''}{number_template.get('number') or factura.get('id')}"
    return True, f"Factura {numero_texto} creada. Pendiente de emitir ante la DIAN."


def emitir_factura_dian_orden(uid, hoja_id):
    """
    Emite ante la DIAN una factura que MyTaller ya creó en Alegra pero que
    quedó 'abierta' (ver facturar_orden). Al emitirla completa CUFE/PDF/XML y
    marca la orden como 'Facturado' en su estado operativo.
    Devuelve (True, mensaje) o (False, mensaje).
    """
    import queries

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return False, "Orden no encontrada."
    if not orden.factura_alegra_id:
        return False, "Esta orden todavía no tiene una factura creada."
    if orden.factura_estado == "emitida":
        return False, "Esta factura ya fue emitida ante la DIAN."

    email, token = obtener_credenciales(uid)
    if not email or not token:
        return False, "Este taller no tiene configurada su cuenta de facturación electrónica."

    ok, msg = emitir_factura_dian(email, token, orden.factura_alegra_id)
    if not ok:
        return False, msg

    factura_completa = obtener_factura(email, token, orden.factura_alegra_id)
    cufe = pdf_url = xml_url = prefijo = numero = None
    if factura_completa:
        cufe = factura_completa.get("stamp", {}).get("cufe") if isinstance(factura_completa.get("stamp"), dict) else None
        pdf_url = factura_completa.get("pdf") if isinstance(factura_completa.get("pdf"), str) else None
        xml_url = factura_completa.get("xml") if isinstance(factura_completa.get("xml"), str) else None
        number_template = factura_completa.get("numberTemplate") if isinstance(factura_completa.get("numberTemplate"), dict) else {}
        prefijo = number_template.get("prefix")
        numero = str(number_template["number"]) if number_template.get("number") is not None else None

    # Copia propia del PDF y del XML timbrado - así no dependen de que el
    # enlace de Alegra siga vivo cuando alguien quiera verlos después.
    pdf_url = _guardar_como_enlace_propio(pdf_url, "application/pdf")
    xml_url = _guardar_como_enlace_propio(xml_url, "application/xml")

    queries.guardar_resultado_factura(
        hoja_id, alegra_id=orden.factura_alegra_id, cufe=cufe, pdf_url=pdf_url, xml_url=xml_url,
        estado="emitida", prefijo=prefijo, numero=numero,
    )
    # La factura electrónica queda emitida: la orden pasa a 'Facturado' en su
    # estado operativo, igual que si se hubiera marcado manualmente.
    queries.marcar_orden_facturada(hoja_id)

    return True, "Factura emitida ante la DIAN."


def anular_factura_orden(uid, hoja_id):
    """
    Emite la nota crédito en Alegra que anula la factura electrónica de una
    orden (cuando el trabajo se anula/devuelve después de facturado). No hace
    nada (y no es un error) si la orden nunca tuvo factura electrónica emitida.
    Devuelve (True, mensaje) o (False, mensaje).
    """
    import queries

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden:
        return False, "Orden no encontrada."
    if orden.factura_estado != "emitida" or not orden.factura_alegra_id:
        return True, "Esta orden no tenía factura electrónica emitida, no se requiere nota crédito."
    if orden.nota_credito_alegra_id:
        return False, "Esta orden ya tiene una nota crédito emitida."

    email, token = obtener_credenciales(uid)
    if not email or not token:
        return False, "Este taller no tiene configurada su cuenta de facturación electrónica."

    contacto_id = obtener_o_crear_contacto_empresa(uid, orden.empresa_id, email, token)
    if not contacto_id:
        return False, "No se pudo obtener el cliente."

    renglones = queries.obtener_items_orden(hoja_id)
    if not renglones:
        return False, "No hay ítems para la nota crédito."

    config = queries.obtener_config_taller(uid)
    iva_activo = bool(config[4]) if config and config[4] is not None else False
    iva_incluido = bool(config[5]) if config and config[5] is not None else False
    iva_tipo_default_mo = config[6] if config and config[6] else "Excluido"
    iva_tipo_default_rep = config[7] if config and config[7] else "Excluido"

    from pdf_utils import IVA_TASA, resolver_iva_tipo

    items_payload = []
    total_orden = 0.0
    for r in renglones:
        etiqueta = resolver_iva_tipo(r.iva_tipo)
        if etiqueta is None:
            etiqueta = iva_tipo_default_mo if r.tipo_item == "Mano de Obra" else iva_tipo_default_rep
        if not iva_activo:
            etiqueta = "Excluido"
        iva_porcentaje = IVA_TASA.get(etiqueta, 0.0)

        item_id = crear_item_ad_hoc(email, token, r.descripcion, float(r.precio_venta))
        if not item_id:
            continue
        items_payload.append(_construir_item_payload(item_id, r.precio_venta, iva_porcentaje, iva_incluido, email, token))
        total_orden += float(r.precio_venta or 0)

    if not items_payload:
        return False, "No hay ítems válidos para la nota crédito."

    nota = crear_nota_credito(email, token, orden.factura_alegra_id, contacto_id, items_payload, total_orden)
    if not nota:
        return False, "La nota crédito fue rechazada. Revisa el error mostrado arriba."

    pdf_url_nc = nota.get("pdf") if isinstance(nota.get("pdf"), str) else None
    xml_url_nc = nota.get("xml") if isinstance(nota.get("xml"), str) else None
    number_template_nc = nota.get("numberTemplate") if isinstance(nota.get("numberTemplate"), dict) else {}
    if not pdf_url_nc or not xml_url_nc:
        nota_completa = obtener_nota_credito(email, token, nota.get("id"))
        if nota_completa:
            if not pdf_url_nc:
                pdf_url_nc = nota_completa.get("pdf") if isinstance(nota_completa.get("pdf"), str) else None
            if not xml_url_nc:
                xml_url_nc = nota_completa.get("xml") if isinstance(nota_completa.get("xml"), str) else None
            if not number_template_nc and isinstance(nota_completa.get("numberTemplate"), dict):
                number_template_nc = nota_completa["numberTemplate"]

    # Copia propia del PDF y del XML de la nota crédito - mismo motivo que en
    # la factura: el enlace de Alegra vence, esta copia no.
    pdf_url_nc = _guardar_como_enlace_propio(pdf_url_nc, "application/pdf")
    xml_url_nc = _guardar_como_enlace_propio(xml_url_nc, "application/xml")

    queries.guardar_nota_credito(
        hoja_id, nota.get("id"), pdf_url=pdf_url_nc, xml_url=xml_url_nc,
        prefijo=number_template_nc.get("prefix"),
        numero=str(number_template_nc["number"]) if number_template_nc.get("number") is not None else None,
    )
    mensaje_numero = f"{number_template_nc.get('prefix') or ''}{number_template_nc.get('number') or nota.get('id')}"
    return True, f"Nota crédito emitida ({mensaje_numero})."


@st.cache_data(ttl=300, show_spinner=False)
def _factura_cache(email, token, factura_id):
    """Envoltorio cacheado (5 min) de obtener_factura(), para poder refrescar
    enlaces automáticamente en cada render sin golpear la API de Alegra en
    cada interacción del usuario con la página."""
    return obtener_factura(email, token, factura_id)


@st.cache_data(ttl=300, show_spinner=False)
def _nota_credito_cache(email, token, nota_id):
    """Envoltorio cacheado (5 min) de obtener_nota_credito(), mismo motivo que _factura_cache()."""
    return obtener_nota_credito(email, token, nota_id)


def _es_copia_propia(url):
    """True si el enlace ya contiene el archivo adentro (no depende de que
    Alegra lo siga teniendo) - no hace falta pedir nada más para ese caso."""
    return bool(url) and url.startswith("data:")


def refrescar_url_factura_orden(uid, hoja_id):
    """
    Devuelve el enlace para abrir el PDF y el XML de la factura de esta
    orden. Si ya se guardó una copia propia (lo normal desde que se
    creó/emitió la factura), la devuelve directamente sin pedirle nada a
    Alegra. Si todavía no tiene copia guardada, la pide a Alegra una vez
    (con caché de 5 min) y la deja guardada para la próxima vez.
    Devuelve (pdf_url, xml_url), o (None, None) si no hay factura.
    """
    import queries

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden or not orden.factura_alegra_id:
        return None, None
    if _es_copia_propia(orden.factura_pdf_url):
        return orden.factura_pdf_url, orden.factura_xml_url
    email, token = obtener_credenciales(uid)
    if not email or not token:
        return orden.factura_pdf_url, orden.factura_xml_url
    factura = _factura_cache(email, token, orden.factura_alegra_id)
    if not factura:
        return orden.factura_pdf_url, orden.factura_xml_url
    pdf_raw = factura.get("pdf") if isinstance(factura.get("pdf"), str) else None
    xml_raw = factura.get("xml") if isinstance(factura.get("xml"), str) else None
    pdf_url = _guardar_como_enlace_propio(pdf_raw, "application/pdf") if pdf_raw else orden.factura_pdf_url
    xml_url = _guardar_como_enlace_propio(xml_raw, "application/xml") if xml_raw else orden.factura_xml_url
    if pdf_url != orden.factura_pdf_url or xml_url != orden.factura_xml_url:
        queries.actualizar_datos_factura(hoja_id, pdf_url=pdf_url, xml_url=xml_url)
    return pdf_url, xml_url


def refrescar_url_nota_credito_orden(uid, hoja_id):
    """Igual que refrescar_url_factura_orden(), pero para la nota crédito de la orden."""
    import queries

    orden = queries.obtener_orden_para_facturar(uid, hoja_id)
    if not orden or not orden.nota_credito_alegra_id:
        return None, None
    if _es_copia_propia(orden.nota_credito_pdf_url):
        return orden.nota_credito_pdf_url, orden.nota_credito_xml_url
    email, token = obtener_credenciales(uid)
    if not email or not token:
        return orden.nota_credito_pdf_url, orden.nota_credito_xml_url
    nota = _nota_credito_cache(email, token, orden.nota_credito_alegra_id)
    if not nota:
        return orden.nota_credito_pdf_url, orden.nota_credito_xml_url
    pdf_raw = nota.get("pdf") if isinstance(nota.get("pdf"), str) else None
    xml_raw = nota.get("xml") if isinstance(nota.get("xml"), str) else None
    pdf_url = _guardar_como_enlace_propio(pdf_raw, "application/pdf") if pdf_raw else orden.nota_credito_pdf_url
    xml_url = _guardar_como_enlace_propio(xml_raw, "application/xml") if xml_raw else orden.nota_credito_xml_url
    if pdf_url != orden.nota_credito_pdf_url or xml_url != orden.nota_credito_xml_url:
        queries.actualizar_pdf_nota_credito(hoja_id, pdf_url, xml_url=xml_url)
    return pdf_url, xml_url
