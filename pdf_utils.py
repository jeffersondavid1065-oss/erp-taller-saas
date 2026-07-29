"""
Utilidades para generar PDFs profesionales estilo factura moderna para MyTaller.
Diseño limpio, moderno, con layout profesional de factura estándar.
"""

from fpdf import FPDF
import pandas as pd
from datetime import datetime


def generar_pdf_orden_profesional(
    taller_nombre,
    taller_nit="",
    taller_telefono="",
    taller_direccion="",
    taller_email="",
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
    """
    Genera un PDF profesional estilo factura moderna.
    
    Diseño:
    - Header con logo placeholder y datos del taller
    - Información de factura (número, fecha)
    - Secciones: FACTURAR A, DETALLES, PAGO
    - Tabla de ítems limpia
    - Totales bien organizados
    """
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)
    
    # Colores
    color_gris_header = (80, 80, 80)
    color_gris_texto = (51, 51, 51)
    color_azul = (68, 114, 196)
    color_gris_fondo = (242, 242, 242)
    
    # ==========================================
    # HEADER: LOGO + INFO TALLER vs FACTURA #
    # ==========================================
    # Columna izquierda: Logo placeholder + info taller
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*color_gris_header)
    
    # Placeholder para logo (rectángulo gris)
    pdf.set_fill_color(150, 150, 150)
    pdf.rect(15, 15, 20, 20, "F")
    pdf.set_xy(35, 18)
    pdf.cell(60, 5, taller_nombre, ln=True)
    
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_x(35)
    pdf.cell(60, 4, taller_direccion if taller_direccion else "Dirección", ln=True)
    
    if taller_nit:
        pdf.set_x(35)
        pdf.cell(60, 4, f"NIT: {taller_nit}", ln=True)
    
    # Columna derecha: Factura # y Fecha
    pdf.set_xy(140, 15)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*color_gris_header)
    pdf.cell(50, 5, f"Factura# {hoja_id:05d}" if hoja_id else "Factura#", ln=True)
    
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(140, 21)
    pdf.cell(50, 4, "Fecha de emisión", ln=True)
    
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(140, 25)
    pdf.cell(50, 4, fecha if fecha else "dd/mm/aaaa", ln=True)
    
    # Línea separadora
    pdf.set_draw_color(*color_gris_header)
    pdf.set_line_width(1)
    pdf.line(15, 37, 195, 37)
    
    pdf.ln(8)
    
    # ==========================================
    # TITULO Y SUBTÍTULO
    # ==========================================
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*color_gris_header)
    pdf.cell(0, 8, taller_nombre, ln=True)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "Comprobante de servicio autorizado / Cotización", ln=True)
    
    pdf.ln(5)
    
    # ==========================================
    # SECCIONES: FACTURAR A | DETALLES | PAGO
    # ==========================================
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*color_gris_header)
    
    # Ancho de columnas
    col_width = 55
    
    # Headers
    pdf.set_x(15)
    pdf.cell(col_width, 5, "FACTURAR A", ln=False)
    pdf.cell(col_width, 5, "DETALLES", ln=False)
    pdf.cell(col_width, 5, "PAGO", ln=True)
    
    # Línea separadora
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    y_inicio = pdf.get_y()
    pdf.line(15, y_inicio, 195, y_inicio)
    
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*color_gris_texto)
    
    # Contenido secciones
    # Facturar A
    pdf.set_xy(15, pdf.get_y() + 1)
    pdf.multi_cell(col_width - 5, 3, f"{cliente}\n{cliente_nit if cliente_nit else 'NIT: ---'}", border=0)
    
    y_detalles = pdf.get_y()
    
    # Detalles (vuelve a escribir la posición Y correcta)
    pdf.set_xy(70, y_detalles - 12)
    pdf.multi_cell(col_width - 5, 3, "Cambio de aceite,\nreparación y\nmantenimiento", border=0)
    
    # Pago
    pdf.set_xy(125, y_detalles - 12)
    if estado and estado.lower() == "facturado":
        fecha_pago = "Pagado"
    else:
        fecha_pago = fecha if fecha else "dd/mm/aaaa"
    pdf.multi_cell(col_width - 5, 3, f"Vencimiento\n{fecha_pago}", border=0)
    
    pdf.ln(8)
    
    # ==========================================
    # TABLA DE ARTÍCULOS
    # ==========================================
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*color_gris_header)
    
    # Headers de tabla
    pdf.set_x(15)
    pdf.cell(90, 6, "ARTÍCULOS", ln=False)
    pdf.cell(25, 6, "CANT.", ln=False, align="C")
    pdf.cell(30, 6, "PRECIOS", ln=False, align="R")
    pdf.cell(30, 6, "MONTO", ln=True, align="R")
    
    # Línea
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*color_gris_texto)
    
    # Items
    if df_items is not None and not df_items.empty:
        for index, row in df_items.iterrows():
            desc = f"{row.get('descripcion', '')}"
            if row.get('tipo_item'):
                desc = f"[{row['tipo_item']}] {desc}"
            if row.get('mecanico') and row['mecanico'] != '':
                desc += f" ({row['mecanico']})"
            
            cantidad = row.get('cantidad', 1) if 'cantidad' in row else 1
            precio_unitario = float(row.get('precio_venta', 0)) / cantidad if cantidad > 0 else float(row.get('precio_venta', 0))
            subtotal = float(row.get('precio_venta', 0))
            
            # Fila de item
            pdf.set_x(15)
            pdf.cell(90, 5, desc[:70], ln=False)
            pdf.cell(25, 5, f"{cantidad}", ln=False, align="C")
            pdf.cell(30, 5, f"${precio_unitario:,.0f}".replace(",", "."), ln=False, align="R")
            pdf.cell(30, 5, f"${subtotal:,.0f}".replace(",", "."), ln=True, align="R")
            
            # Línea separadora sutil
            pdf.set_draw_color(240, 240, 240)
            pdf.set_line_width(0.2)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    
    pdf.ln(3)
    
    # ==========================================
    # TOTALES
    # ==========================================
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*color_gris_texto)
    
    # Alineados a la derecha
    if incluir_iva:
        subtotal_sin_iva = total / 1.19
        iva = total - subtotal_sin_iva
        
        pdf.set_x(120)
        pdf.cell(45, 5, "Subtotal", ln=False)
        pdf.cell(30, 5, f"${subtotal_sin_iva:,.2f}".replace(",", "."), ln=True, align="R")
        
        pdf.set_x(120)
        pdf.cell(45, 5, "Tax (IVA)", ln=False)
        pdf.cell(30, 5, f"${iva:,.2f}".replace(",", "."), ln=True, align="R")
    
    # Línea
    pdf.set_draw_color(200, 200, 200)
    pdf.line(120, pdf.get_y(), 195, pdf.get_y())
    
    # Total
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*color_gris_header)
    pdf.set_x(120)
    pdf.cell(45, 8, "Total a pagar", ln=False)
    pdf.cell(30, 8, f"${total:,.0f}".replace(",", "."), ln=True, align="R")
    
    pdf.ln(10)
    
    # ==========================================
    # PIE DE PÁGINA
    # ==========================================
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "¿Deseas personalizar aún más la factura?", ln=True)
    pdf.cell(0, 4, "Agrega impuestos, descuentos y cobros por servicio.", ln=True)
    
    if estado and estado.lower() == "facturado":
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(200, 53, 69)
        pdf.ln(2)
        pdf.cell(0, 3, "Documento válido para propósitos fiscales - DIAN", ln=True)
    
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.ln(10)
    pdf.cell(0, 3, f"Página 1", ln=True, align="C")
    
    return bytes(pdf.output())


# Función legacy para compatibilidad
def generar_pdf_orden(taller, hoja_id, fecha, cliente, nit, placa, estado, df_items, total):
    """Función legacy — mantiene compatibilidad con código existente."""
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
        incluir_iva=False
    )
