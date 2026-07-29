"""
Utilidades para generar PDFs profesionales de órdenes y facturas en MyTaller.
Diseño moderno, colores corporativos, formato de factura estándar DIAN.
"""

from fpdf import FPDF
import pandas as pd
from datetime import datetime


class PDFOrdenProfesional(FPDF):
    """Clase personalizada para PDF de órdenes con diseño profesional."""
    
    def __init__(self):
        super().__init__()
        # Colores corporativos
        self.color_principal = (31, 78, 120)      # Azul oscuro
        self.color_secundario = (68, 114, 196)    # Azul claro
        self.color_texto = (51, 51, 51)           # Gris oscuro
        self.color_fondo = (242, 242, 242)        # Gris muy claro
    
    def header(self):
        """Header personalizado - NO se llama automáticamente en cada página."""
        pass
    
    def footer(self):
        """Pie de página - NO se llama automáticamente en cada página."""
        pass


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
    Genera un PDF profesional y moderno de orden/factura/cotización.
    
    Diseño:
    - Header elegante con colores corporativos
    - Secciones bien definidas
    - Tabla clara con ítem, descripción, técnico, valor
    - Totales destacados
    - Pie de página profesional
    """
    
    pdf = PDFOrdenProfesional()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)
    
    # ==========================================
    # HEADER PROFESIONAL
    # ==========================================
    pdf.set_fill_color(31, 78, 120)  # Azul oscuro
    pdf.rect(10, 10, 190, 28, "F")
    
    # Nombre del taller
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(255, 255, 255)  # Blanco
    pdf.set_xy(15, 15)
    pdf.cell(0, 10, taller_nombre, ln=True)
    
    # Tipo de documento
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(200, 200, 200)  # Gris claro
    pdf.set_xy(15, 25)
    if estado and estado.lower() == "facturado":
        tipo_doc = "FACTURA DE VENTA"
    else:
        tipo_doc = "COTIZACIÓN / COMPROBANTE DE SERVICIO"
    pdf.cell(0, 4, tipo_doc, ln=True)
    
    pdf.ln(6)
    
    # ==========================================
    # INFORMACIÓN DEL TALLER (pequeña)
    # ==========================================
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    
    info_taller = []
    if taller_nit:
        info_taller.append(f"NIT: {taller_nit}")
    if taller_telefono:
        info_taller.append(f"Tel: {taller_telefono}")
    if taller_email:
        info_taller.append(f"Email: {taller_email}")
    
    pdf.set_x(15)
    pdf.cell(0, 3, " | ".join(info_taller), ln=True)
    
    if taller_direccion:
        pdf.set_x(15)
        pdf.cell(0, 3, f"Dirección: {taller_direccion}", ln=True)
    
    pdf.ln(2)
    
    # ==========================================
    # DATOS PRINCIPALES EN DOS COLUMNAS
    # ==========================================
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(31, 78, 120)  # Azul oscuro
    
    # Columna izquierda: Orden, Cliente, NIT
    pdf.set_xy(15, pdf.get_y())
    pdf.cell(95, 5, f"ORDEN N°: {hoja_id}", ln=False)
    
    # Columna derecha: Fecha, Placa, Estado
    pdf.set_x(110)
    pdf.cell(90, 5, f"Fecha: {fecha}", ln=True)
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(51, 51, 51)
    
    pdf.set_xy(15, pdf.get_y())
    pdf.cell(95, 4, f"Cliente: {cliente}", ln=False)
    pdf.set_x(110)
    pdf.cell(90, 4, f"Placa: {placa}", ln=True)
    
    pdf.set_xy(15, pdf.get_y())
    pdf.cell(95, 4, f"NIT/CC: {cliente_nit}", ln=False)
    
    if estado:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(220, 53, 69)  # Rojo
        pdf.set_x(110)
        estado_display = "FACTURADO" if estado.lower() == "facturado" else estado
        pdf.cell(90, 4, f"Estado: {estado_display}", ln=True)
    else:
        pdf.ln(4)
    
    pdf.ln(3)
    
    # ==========================================
    # TABLA DE ÍTEMS (PROFESIONAL)
    # ==========================================
    # Header de tabla
    pdf.set_fill_color(68, 114, 196)  # Azul claro
    pdf.set_text_color(255, 255, 255)  # Blanco
    pdf.set_font("Helvetica", "B", 9)
    
    col_desc = 90
    col_cant = 20
    col_valor = 35
    col_total = 45
    
    pdf.set_xy(15, pdf.get_y())
    pdf.cell(col_desc, 6, "Descripción", border=1, align="L", fill=True)
    pdf.cell(col_cant, 6, "Cant.", border=1, align="C", fill=True)
    pdf.cell(col_valor, 6, "V. Unitario", border=1, align="R", fill=True)
    pdf.cell(col_total, 6, "Subtotal", border=1, align="R", fill=True, ln=True)
    
    # Items
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(51, 51, 51)
    
    if df_items is not None and not df_items.empty:
        for index, row in df_items.iterrows():
            # Descripción con tipo de ítem
            desc = f"{row.get('descripcion', '')}"
            if row.get('tipo_item'):
                desc = f"[{row['tipo_item']}] {desc}"
            if row.get('mecanico') and row['mecanico'] != '':
                desc += f"\n  Técnico: {row['mecanico']}"
            
            cantidad = row.get('cantidad', 1) if 'cantidad' in row else 1
            precio_unitario = float(row.get('precio_venta', 0)) / cantidad if cantidad > 0 else float(row.get('precio_venta', 0))
            subtotal = float(row.get('precio_venta', 0))
            
            # Altura para multilinea
            altura = 6 if "\n" not in desc else 10
            
            pdf.set_xy(15, pdf.get_y())
            pdf.multi_cell(col_desc, altura, desc[:45], border=1, align="L")
            
            y_actual = pdf.get_y() - altura
            pdf.set_xy(15 + col_desc, y_actual)
            pdf.cell(col_cant, altura, f"{cantidad}", border=1, align="C")
            pdf.cell(col_valor, altura, f"${precio_unitario:,.0f}".replace(",", "."), border=1, align="R")
            pdf.cell(col_total, altura, f"${subtotal:,.0f}".replace(",", "."), border=1, align="R", ln=True)
    
    pdf.ln(2)
    
    # ==========================================
    # TOTALES DESTACADOS
    # ==========================================
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(31, 78, 120)  # Azul oscuro
    
    if incluir_iva:
        subtotal_sin_iva = total / 1.19
        iva = total - subtotal_sin_iva
        
        pdf.set_x(110)
        pdf.cell(35, 6, "Subtotal:", border=0, align="R", fill=False)
        pdf.cell(45, 6, f"${subtotal_sin_iva:,.0f}".replace(",", "."), border=0, align="R", fill=False, ln=True)
        
        pdf.set_x(110)
        pdf.cell(35, 6, "IVA (19%):", border=0, align="R", fill=False)
        pdf.cell(45, 6, f"${iva:,.0f}".replace(",", "."), border=0, align="R", fill=False, ln=True)
    
    # Total principal
    pdf.set_x(110)
    pdf.cell(35, 7, "TOTAL:", border=1, align="R", fill=True)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(45, 7, f"${total:,.0f}".replace(",", "."), border=1, align="R", fill=True, ln=True)
    
    pdf.ln(4)
    
    # ==========================================
    # PIE DE PÁGINA PROFESIONAL
    # ==========================================
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.ln(10)
    pdf.cell(0, 4, "Gracias por confiar en nuestros servicios.", ln=True, align="C")
    pdf.cell(0, 4, "Conserve este documento para reclamar su vehículo.", ln=True, align="C")
    
    if estado and estado.lower() == "facturado":
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(200, 53, 69)  # Rojo
        pdf.ln(2)
        pdf.cell(0, 3, "Documento válido para propósitos fiscales - DIAN", ln=True, align="C")
    
    # Línea decorativa final
    pdf.set_draw_color(68, 114, 196)  # Azul claro
    pdf.line(15, pdf.get_y() + 2, 195, pdf.get_y() + 2)
    
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
