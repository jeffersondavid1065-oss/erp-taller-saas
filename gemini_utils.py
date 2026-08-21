"""
Módulo para leer facturas con Google Gemini y extraer productos automáticamente.
Usa el nuevo SDK google-genai con modelos Gemini 3.x
"""

import streamlit as st
import json
import re
import os
from PIL import Image
import io
from db import mensaje_error_amigable


def configurar_cliente():
    """Configura el cliente de Gemini con la key de los secrets (o de
    GEMINI_API_KEY como variable de entorno simple, para hostings que no
    generan un .streamlit/secrets.toml como sí hace Streamlit Community
    Cloud)."""
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or st.secrets["gemini"]["api_key"]
        client = genai.Client(api_key=api_key)
        return client
    except Exception as e:
        st.error(mensaje_error_amigable(e, "conectar con el lector de facturas por IA"))
        return None


PROMPT_FACTURA = """
Analiza esta factura de compra y extrae TODOS los productos/artículos que aparecen.

Devuelve ÚNICAMENTE un JSON válido con este formato exacto, sin texto adicional ni markdown:
{
    "productos": [
        {
            "nombre": "nombre del producto",
            "cantidad": número,
            "costo_unitario": número,
            "subtotal": número
        }
    ],
    "proveedor": "nombre del proveedor si aparece o null",
    "numero_factura": "número de factura si aparece o null",
    "total_factura": número
}

Reglas importantes:
- cantidad debe ser un número entero
- costo_unitario debe ser el precio por unidad (sin signos de moneda ni puntos de miles)
- subtotal debe ser cantidad * costo_unitario
- Si no puedes leer un valor numérico, usa 0
- Incluye TODOS los productos de la factura
- Los precios en Colombia usan puntos como separador de miles: 15.000 = 15000
- NO incluyas ```json ni ningún markdown, solo el JSON puro
"""


def leer_factura_imagen(imagen_bytes):
    """Lee una imagen de factura y extrae los productos usando Gemini."""
    client = configurar_cliente()
    if not client:
        return None

    try:
        from google.genai import types

        imagen = Image.open(io.BytesIO(imagen_bytes))
        buf = io.BytesIO()
        imagen.save(buf, format="JPEG")
        buf.seek(0)
        img_bytes = buf.read()

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                PROMPT_FACTURA
            ]
        )

        texto = response.text.strip()
        texto = re.sub(r'```json\s*', '', texto)
        texto = re.sub(r'```\s*', '', texto)
        texto = texto.strip()

        datos = json.loads(texto)
        return datos

    except json.JSONDecodeError:
        st.error("Gemini no pudo extraer los datos en formato correcto. Intenta con una imagen más clara.")
        return None
    except Exception as e:
        st.error(mensaje_error_amigable(e, "leer la imagen de la factura"))
        return None


PROMPT_RUT = """
Analiza este PDF del RUT (Registro Único Tributario, DIAN Colombia) y extrae los datos
necesarios para registrar el contacto y facturarle electrónicamente.

Devuelve ÚNICAMENTE un JSON válido con este formato exacto, sin texto adicional ni markdown:
{
    "razon_social": "razón social si es persona jurídica, o nombres y apellidos completos si es persona natural",
    "tipo_documento": "NIT" o "CC",
    "numero_documento": "número de identificación, solo dígitos, sin puntos ni el dígito de verificación",
    "digito_verificacion": "dígito de verificación (casilla DV), como texto, o null si no aplica",
    "responsable_iva": true o false, según si en "Responsabilidades tributarias" aparece el código 48
        (Impuesto sobre las ventas - IVA) o cualquier responsabilidad de IVA distinta a "49 - No responsable de IVA"
}

Reglas importantes:
- tipo_documento es "NIT" si el documento identifica una empresa/persona jurídica o un NIT de persona natural,
  "CC" si el RUT identifica a una persona natural por cédula de ciudadanía
- Si no puedes leer un dato con certeza, usa null (o false para responsable_iva)
- NO incluyas ```json ni ningún markdown, solo el JSON puro
"""


def leer_rut_pdf(pdf_bytes):
    """Lee un PDF de RUT (DIAN) y extrae los datos para registrar el contacto usando Gemini."""
    client = configurar_cliente()
    if not client:
        return None

    try:
        from google.genai import types

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                PROMPT_RUT
            ]
        )

        texto = response.text.strip()
        texto = re.sub(r'```json\s*', '', texto)
        texto = re.sub(r'```\s*', '', texto)
        texto = texto.strip()

        datos = json.loads(texto)
        datos["regimen"] = "COMMON_REGIME" if datos.get("responsable_iva") else "SIMPLIFIED_REGIME"
        return datos

    except json.JSONDecodeError:
        st.error("Gemini no pudo extraer los datos en formato correcto. Intenta con un PDF más claro.")
        return None
    except Exception as e:
        st.error(mensaje_error_amigable(e, "leer el PDF del RUT"))
        return None


def leer_factura_pdf(pdf_bytes):
    """Lee un PDF de factura y extrae los productos usando Gemini."""
    client = configurar_cliente()
    if not client:
        return None

    try:
        from google.genai import types

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                PROMPT_FACTURA
            ]
        )

        texto = response.text.strip()
        texto = re.sub(r'```json\s*', '', texto)
        texto = re.sub(r'```\s*', '', texto)
        texto = texto.strip()

        datos = json.loads(texto)
        return datos

    except json.JSONDecodeError:
        st.error("Gemini no pudo extraer los datos en formato correcto. Intenta con una imagen más clara.")
        return None
    except Exception as e:
        st.error(mensaje_error_amigable(e, "leer el PDF de la factura"))
        return None
