"""
Utilidades para generar PDFs profesionales estilo factura moderna para MyTaller.
Diseño limpio, moderno, con layout profesional de factura estándar.
Incluye cálculo de IVA (Colombia) por catálogo de tipos de impuesto, igual al
que usan los sistemas de facturación electrónica colombianos (Excluido,
IVA 0% Exento, IVA 5%, IVA 16%, IVA 19%, Impuesto al Consumo 0%, etc.)
"""

from fpdf import FPDF
import pandas as pd
from datetime import datetime
import os
import requests
from io import BytesIO


# ==========================================================================
# CATÁLOGO DE TIPOS DE IMPUESTO (Colombia)
# Cada ítem (mano de obra, repuesto, producto de inventario) tiene asignado
# uno de estos tipos. La etiqueta es la que se imprime tal cual en la factura.
# ==========================================================================
IVA_OPCIONES = [
    "Excluido",
    "IVA 0% (Exento)",
    "IVA 5%",
    "IVA 16%",
    "IVA 19%",
    "Imp Consumo 0%",
]

IVA_TASA = {
    "Excluido": 0.0,
    "IVA 0% (Exento)": 0.0,
    "IVA 5%": 5.0,
    "IVA 16%": 16.0,
    "IVA 19%": 19.0,
    "Imp Consumo 0%": 0.0,
}


def resolver_iva_tipo(valor):
    """Normaliza un valor de iva_tipo venido de BD (puede ser None, NaN o
    una etiqueta ya válida). Si no es reconocible, retorna None."""
    if valor is None:
        return None
    if isinstance(valor, float) and pd.isna(valor):
        return None
    valor = str(valor).strip()
    return valor if valor in IVA_TASA else None


def calcular_totales_orden(df_items, iva_activo=False, iva_incluido=False,
                            iva_tipo_default_mano_obra="Excluido",
                            iva_tipo_default_repuestos="Excluido"):
    """
    Calcula subtotal, IVA total, total y el desglose por tipo de impuesto
    de una orden, respetando este orden de prioridad para cada ítem:

    1. Tipo de impuesto explícito en el ítem (columna 'iva_tipo'), que a su
       vez puede venir marcado manualmente al agregarlo, o heredado
       directamente del producto de Inventario si el repuesto se tomó del
       almacén propio.
    2. Si el ítem no tiene tipo asignado (NULL), se usa el default de su
       categoría configurado en el taller (iva_tipo_default_mano_obra /
       iva_tipo_default_repuestos según 'tipo_item').
    3. Si el taller tiene iva_activo=False (interruptor maestro apagado),
       se ignora todo lo anterior y ningún ítem paga impuesto.

    Retorna: (subtotal, iva_total, total, desglose_iva)
    donde desglose_iva es un dict {etiqueta: monto_iva} solo con las
    etiquetas que efectivamente generaron un valor de IVA > 0 (para no
    imprimir líneas de "IVA 0%" o "Excluido" vacías en la factura).
    """
    if df_items is None or df_items.empty:
        return 0.0, 0.0, 0.0, {}

    subtotal = 0.0
    iva_total = 0.0
    desglose = {}

    for _, row in df_items.iterrows():
        precio = float(row.get('precio_venta', 0) or 0)
        tipo_item = row.get('tipo_item', '') if hasattr(row, 'get') else ''

        etiqueta = resolver_iva_tipo(row.get('iva_tipo', None) if hasattr(row, 'get') else None)

        if etiqueta is None:
            if tipo_item == 'Mano de Obra':
                etiqueta = resolver_iva_tipo(iva_tipo_default_mano_obra) or "Excluido"
            else:
                etiqueta = resolver_iva_tipo(iva_tipo_default_repuestos) or "Excluido"

        if not iva_activo:
            etiqueta = "Excluido"

        tasa = IVA_TASA.get(etiqueta, 0.0) / 100.0

        if iva_incluido and tasa > 0:
            base = precio / (1 + tasa)
            iva_item = precio - base
        else:
            base = precio
            iva_item = precio * tasa

        subtotal += base
        iva_total += iva_item

        if iva_item > 0:
            desglose[etiqueta] = desglose.get(etiqueta, 0.0) + iva_item

    total = subtotal + iva_total
    desglose_redondeado = {k: round(v, 2) for k, v in desglose.items() if round(v, 2) > 0}
    return round(subtotal, 2), round(iva_total, 2), round(total, 2), desglose_redondeado


def generar_pdf_orden_profesional(
    taller_nombre,
    taller_nit="",
    taller_telefono="",
    taller_direccion="",
    taller_email="",
    taller_logo_path=None,
    hoja_id=None,
    fecha="",
    cliente="",
    cliente_nit="",
    placa="",
    estado="",
    df_items=None,
    total=0,
    subtotal=None,
    desglose_iva=None,
    marca="",
    modelo="",
    es_cotizacion=False
):
    """
    Genera el PDF de la orden/factura, o de una cotización si es_cotizacion=True
    (cambia el rótulo del encabezado, la columna de pago y el pie de página
    para dejar claro que no es un documento fiscal).

    - Si `subtotal` se pasa (no None), se muestra el desglose: Subtotal,
      una línea por cada tipo de impuesto presente en `desglose_iva`
      (dict {etiqueta: monto}, ej. {"IVA 19%": 38000.0}), y Total.
      Se recomienda obtener subtotal/desglose_iva/total con
      calcular_totales_orden() para que sean siempre consistentes con lo
      mostrado en pantalla.
    - Si no se pasan, se muestra únicamente el total (comportamiento para
      talleres sin IVA activo).
    - `marca`/`modelo`: opcionales, texto libre. Si vienen, se imprimen
      debajo de la placa.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Convertir todo a string seguro
    def safe_str(valor, default=""):
        if valor is None:
            return default
        try:
            s = str(valor)
            if "." in s and " " in s:
                s = s.split(" ")[0]
            return s
        except Exception:
            return default

    taller_nombre    = safe_str(taller_nombre, "MyTaller")
    taller_nit       = safe_str(taller_nit)
    taller_telefono  = safe_str(taller_telefono)
    taller_direccion = safe_str(taller_direccion)
    taller_email     = safe_str(taller_email)
    fecha            = safe_str(fecha, "dd/mm/aaaa")
    cliente          = safe_str(cliente)
    cliente_nit      = safe_str(cliente_nit)
    placa            = safe_str(placa)
    estado           = safe_str(estado)
    marca            = safe_str(marca)
    modelo           = safe_str(modelo)
    hoja_id_str      = str(hoja_id).zfill(5) if hoja_id else "00000"
    etiqueta_doc     = "Cotizacion" if es_cotizacion else "Factura"

    mostrar_desglose_iva = subtotal is not None
    desglose_iva = desglose_iva or {}

    # Colores
    GRIS_OSCURO  = (80, 80, 80)
    GRIS_MEDIO   = (120, 120, 120)
    GRIS_CLARO   = (200, 200, 200)
    NEGRO        = (30, 30, 30)

    # ==========================================
    # HEADER: LOGO | INFO TALLER | FACTURA #
    # ==========================================
    y_header = 12

    # Logo (imagen real o placeholder gris)
    logo_dibujado = False
    if taller_logo_path and os.path.exists(taller_logo_path):
        try:
            pdf.image(taller_logo_path, x=12, y=y_header, w=22, h=22)
            logo_dibujado = True
        except Exception:
            pass

    if not logo_dibujado:
        pdf.set_fill_color(180, 180, 180)
        pdf.rect(12, y_header, 22, 22, "F")
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(12, y_header + 8)
        pdf.cell(22, 4, "LOGOTIPO", align="C")

    # Nombre y datos del taller (junto al logo)
    pdf.set_xy(38, y_header)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.cell(80, 5, taller_nombre)
    pdf.ln(0)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_MEDIO)
    pdf.set_xy(38, y_header + 6)
    pdf.cell(80, 4, taller_direccion if taller_direccion else "Direccion, Ciudad, Pais")
    pdf.ln(0)

    if taller_nit:
        pdf.set_xy(38, y_header + 10)
        pdf.cell(80, 4, f"NIT: {taller_nit}")
        pdf.ln(0)

    if taller_telefono:
        pdf.set_xy(38, y_header + 14)
        pdf.cell(80, 4, f"Tel: {taller_telefono}")
        pdf.ln(0)

    # Factura # y fecha (alineado a la derecha)
    pdf.set_xy(130, y_header)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.cell(65, 5, f"{etiqueta_doc}# {hoja_id_str}", align="R")
    pdf.ln(0)

    pdf.set_xy(130, y_header + 7)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_MEDIO)
    pdf.cell(65, 4, "Fecha de cotizacion" if es_cotizacion else "Fecha de emision", align="R")
    pdf.ln(0)

    pdf.set_xy(130, y_header + 12)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.cell(65, 4, fecha, align="R")

    # Línea separadora
    pdf.set_draw_color(*GRIS_OSCURO)
    pdf.set_line_width(0.8)
    pdf.line(12, 37, 198, 37)
    pdf.ln(0)

    # ==========================================
    # TITULO
    # ==========================================
    pdf.set_xy(12, 41)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NEGRO)
    pdf.cell(0, 8, taller_nombre)
    pdf.ln(0)

    pdf.set_xy(12, 50)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GRIS_MEDIO)
    pdf.cell(0, 5, "Agrega un mensaje para el cliente aqui.")

    # ==========================================
    # TRES COLUMNAS SEPARADAS: FACTURAR A | DETALLES | PAGO
    # ==========================================
    y_cols = 62
    col1_x = 12
    col2_x = 80
    col3_x = 148
    col_ancho = 60

    # Headers de columnas
    pdf.set_draw_color(*GRIS_CLARO)
    pdf.set_line_width(0.3)
    pdf.line(12, y_cols, 198, y_cols)
    pdf.ln(0)

    pdf.set_xy(col1_x, y_cols + 2)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.cell(col_ancho, 4, "FACTURAR A")

    pdf.set_xy(col2_x, y_cols + 2)
    pdf.cell(col_ancho, 4, "DETALLES")

    pdf.set_xy(col3_x, y_cols + 2)
    pdf.cell(col_ancho, 4, "PAGO")

    # Contenido columna 1: Cliente
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.set_xy(col1_x, y_cols + 8)
    pdf.cell(col_ancho - 5, 4, cliente)
    pdf.set_xy(col1_x, y_cols + 13)
    pdf.cell(col_ancho - 5, 4, f"NIT: {cliente_nit}" if cliente_nit else "NIT: ---")
    pdf.set_xy(col1_x, y_cols + 18)
    pdf.cell(col_ancho - 5, 4, f"Placa: {placa}" if placa else "")
    if marca or modelo:
        marca_modelo_txt = " / ".join(v for v in (marca, modelo) if v)
        pdf.set_xy(col1_x, y_cols + 23)
        pdf.cell(col_ancho - 5, 4, f"Marca/Modelo: {marca_modelo_txt}")

    # Contenido columna 2: Detalles (descripción del trabajo)
    pdf.set_xy(col2_x, y_cols + 8)
    pdf.cell(col_ancho - 5, 4, "Servicio automotriz")
    pdf.set_xy(col2_x, y_cols + 13)
    pdf.cell(col_ancho - 5, 4, "y mantenimiento")

    # Contenido columna 3: Pago
    if es_cotizacion:
        estado_pago = "Precios sujetos a cambio"
    elif estado.lower() == "facturado":
        estado_pago = "PAGADO"
    else:
        estado_pago = "Por cobrar"

    pdf.set_xy(col3_x, y_cols + 8)
    pdf.cell(col_ancho, 4, f"Fecha {fecha}" if es_cotizacion else f"Vencimiento {fecha}")
    pdf.set_xy(col3_x, y_cols + 13)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.cell(col_ancho, 4, f"${total:,.0f}".replace(",", "."))

    pdf.set_xy(col3_x, y_cols + 19)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_MEDIO)
    pdf.cell(col_ancho, 4, estado_pago)

    # ==========================================
    # TABLA DE ARTÍCULOS
    # ==========================================
    y_tabla = y_cols + 32
    pdf.set_draw_color(*GRIS_CLARO)
    pdf.line(12, y_tabla, 198, y_tabla)

    pdf.set_xy(12, y_tabla + 2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*GRIS_OSCURO)
    pdf.cell(95, 5, "ARTICULOS")
    pdf.cell(25, 5, "CANT.", align="C")
    pdf.cell(33, 5, "PRECIOS", align="R")
    pdf.cell(33, 5, "MONTO", align="R")

    pdf.set_draw_color(*GRIS_CLARO)
    pdf.line(12, y_tabla + 8, 198, y_tabla + 8)

    y_item = y_tabla + 10
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_OSCURO)

    if df_items is not None and not df_items.empty:
        for idx, row in df_items.iterrows():
            desc = safe_str(row.get('descripcion', ''))
            tipo = safe_str(row.get('tipo_item', ''))
            mec  = safe_str(row.get('mecanico', ''))

            linea1 = f"[{tipo}] {desc}"[:68] if tipo else desc[:68]
            linea2 = f"Tecnico: {mec}" if mec else ""

            cantidad = 1
            subtotal_item = float(row.get('precio_venta', 0))
            precio_u = subtotal_item

            pdf.set_xy(12, y_item)
            pdf.cell(95, 5, linea1)
            pdf.cell(25, 5, str(cantidad), align="C")
            pdf.cell(33, 5, f"${precio_u:,.0f}".replace(",", "."), align="R")
            pdf.cell(33, 5, f"${subtotal_item:,.0f}".replace(",", "."), align="R")
            y_item += 5

            if linea2:
                pdf.set_xy(12, y_item)
                pdf.set_text_color(*GRIS_MEDIO)
                pdf.cell(95, 4, linea2)
                pdf.set_text_color(*GRIS_OSCURO)
                y_item += 4

            # Línea separadora sutil
            pdf.set_draw_color(230, 230, 230)
            pdf.line(12, y_item, 198, y_item)
            y_item += 1

    # ==========================================
    # TOTALES
    # ==========================================
    y_totales = y_item + 4
    pdf.set_draw_color(*GRIS_CLARO)

    if mostrar_desglose_iva:
        pdf.set_xy(130, y_totales)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRIS_OSCURO)
        pdf.cell(35, 5, "Subtotal")
        pdf.cell(33, 5, f"${subtotal:,.0f}".replace(",", "."), align="R")
        y_totales += 5

        for etiqueta, monto in desglose_iva.items():
            pdf.set_xy(130, y_totales)
            pdf.cell(35, 5, etiqueta)
            pdf.cell(33, 5, f"${monto:,.0f}".replace(",", "."), align="R")
            y_totales += 5

    pdf.line(130, y_totales, 198, y_totales)
    y_totales += 1

    pdf.set_xy(130, y_totales)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NEGRO)
    pdf.cell(35, 7, "Total a pagar")
    pdf.cell(33, 7, f"${total:,.0f}".replace(",", "."), align="R")

    # ==========================================
    # PIE DE PÁGINA
    # ==========================================
    y_pie = y_totales + 20
    pdf.set_xy(12, y_pie)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GRIS_MEDIO)
    pdf.cell(0, 4, "Gracias por confiar en nuestros servicios. Conserve este documento.")
    y_pie += 4

    if es_cotizacion:
        pdf.set_xy(12, y_pie)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(180, 120, 20)
        pdf.cell(0, 3, "Cotizacion sin valor fiscal - no reemplaza una factura")
        y_pie += 4

    if estado.lower() == "facturado":
        pdf.set_xy(12, y_pie)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(180, 40, 40)
        pdf.cell(0, 3, "Documento valido para propositos fiscales - DIAN")
        y_pie += 4

    pdf.set_xy(12, y_pie + 5)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 3, "Pagina 1", align="C")

    return bytes(pdf.output())


def generar_pdf_orden(taller, hoja_id, fecha, cliente, nit, placa, estado, df_items, total):
    """Función legacy para compatibilidad (sin desglose de IVA)."""
    return generar_pdf_orden_profesional(
        taller_nombre=taller,
        hoja_id=hoja_id,
        fecha=fecha,
        cliente=cliente,
        cliente_nit=nit,
        placa=placa,
        estado=estado,
        df_items=df_items,
        total=total,
    )
