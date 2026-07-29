"""
Utilidades para generar PDFs profesionales estilo factura moderna para MyTaller.
Diseño limpio, moderno, con layout profesional de factura estándar.
"""

from fpdf import FPDF
import pandas as pd
from datetime import datetime
import os
import requests
from io import BytesIO


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
    incluir_iva=False
):
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
    hoja_id_str      = str(hoja_id).zfill(5) if hoja_id else "00000"

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
    pdf.cell(65, 5, f"Factura# {hoja_id_str}", align="R")
    pdf.ln(0)

    pdf.set_xy(130, y_header + 7)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_MEDIO)
    pdf.cell(65, 4, "Fecha de emision", align="R")
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

    # Contenido columna 2: Detalles (descripción del trabajo)
    pdf.set_xy(col2_x, y_cols + 8)
    pdf.cell(col_ancho - 5, 4, "Servicio automotriz")
    pdf.set_xy(col2_x, y_cols + 13)
    pdf.cell(col_ancho - 5, 4, "y mantenimiento")

    # Contenido columna 3: Pago
    if estado.lower() == "facturado":
        estado_pago = "PAGADO"
    else:
        estado_pago = "Por cobrar"

    pdf.set_xy(col3_x, y_cols + 8)
    pdf.cell(col_ancho, 4, f"Vencimiento {fecha}")
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
            subtotal = float(row.get('precio_venta', 0))
            precio_u = subtotal

            pdf.set_xy(12, y_item)
            pdf.cell(95, 5, linea1)
            pdf.cell(25, 5, str(cantidad), align="C")
            pdf.cell(33, 5, f"${precio_u:,.0f}".replace(",", "."), align="R")
            pdf.cell(33, 5, f"${subtotal:,.0f}".replace(",", "."), align="R")
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

    if incluir_iva:
        subtotal_sin_iva = total / 1.19
        iva = total - subtotal_sin_iva

        pdf.set_xy(130, y_totales)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRIS_OSCURO)
        pdf.cell(35, 5, "Subtotal")
        pdf.cell(33, 5, f"${subtotal_sin_iva:,.0f}".replace(",", "."), align="R")
        y_totales += 5

        pdf.set_xy(130, y_totales)
        pdf.cell(35, 5, "Tax (IVA 19%)")
        pdf.cell(33, 5, f"${iva:,.0f}".replace(",", "."), align="R")
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
    """Función legacy para compatibilidad."""
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
