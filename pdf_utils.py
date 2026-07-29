"""
Utilidades para generar PDFs de órdenes y facturas en MyTaller.
Reutilizable en Expediente, Recepción, Aceites/Flotas, etc.
"""

from fpdf import FPDF
import pandas as pd


def generar_pdf_orden_mejorado(
    taller_nombre,
    taller_telefono="",
    taller_direccion="",
    taller_email="",
    taller_nit="",
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
    Genera un PDF profesional de orden/factura/cotización.
    
    Parámetros:
    -----------
    taller_nombre : str
        Nombre del taller
    taller_telefono : str
        Teléfono del taller
    taller_direccion : str
        Dirección del taller
    taller_email : str
        Email del taller
    taller_nit : str
        NIT del taller (para facturación oficial)
    hoja_id : int
        Número de orden
    fecha : str
        Fecha de la orden
    cliente : str
        Nombre de la empresa/cliente
    cliente_nit : str
        NIT del cliente
    placa : str
        Placa del vehículo
    estado : str
        Estado de la orden (determina si es Cotización o Factura)
    df_items : DataFrame
        Dataframe con columnas: tipo_item, descripcion, mecanico, precio_venta, costo_compra (opcional)
    total : float
        Total a cobrar
    incluir_iva : bool
        Si incluir desglose de IVA (19% en Colombia)
    
    Retorna:
    --------
    bytes: Contenido del PDF en formato bytes
    """
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Título principal
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, taller_nombre, ln=True, align="C")
    
    # Determinar tipo de documento según estado
    if estado and estado.lower() == "facturado":
        tipo_documento = "FACTURA DE VENTA"
    else:
        tipo_documento = "COTIZACIÓN / COMPROBANTE DE SERVICIO"
    
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, tipo_documento, ln=True, align="C")
    
    # Datos del taller (lado izquierdo superior)
    pdf.set_font("Helvetica", "", 8)
    if taller_nit:
        pdf.cell(0, 4, f"NIT: {taller_nit}", ln=True)
    if taller_telefono:
        pdf.cell(0, 4, f"Teléfono: {taller_telefono}", ln=True)
    if taller_direccion:
        pdf.cell(0, 4, f"Dirección: {taller_direccion}", ln=True)
    if taller_email:
        pdf.cell(0, 4, f"Email: {taller_email}", ln=True)
    
    pdf.ln(3)
    
    # Línea separadora
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    
    # Datos principales (orden, fecha, cliente)
    pdf.set_font("Helvetica", "B", 11)
    col_width = 95
    pdf.cell(col_width, 6, f"Orden N°: {hoja_id}", 0, 0)
    pdf.cell(col_width, 6, f"Fecha: {fecha}", 0, 1, align="R")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(col_width, 6, f"Cliente: {cliente}", 0, 0)
    pdf.cell(col_width, 6, f"Placa: {placa}", 0, 1, align="R")
    
    pdf.cell(col_width, 6, f"NIT/CC: {cliente_nit}", 0, 0)
    if estado:
        pdf.set_font("Helvetica", "B", 9)
        estado_display = estado if estado.lower() != "facturado" else "FACTURADO"
        pdf.cell(col_width, 6, f"Estado: {estado_display}", 0, 1, align="R")
    else:
        pdf.ln(6)
    
    pdf.ln(3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    
    # Tabla de ítems
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(110, 7, "Descripción", 1, 0)
    pdf.cell(35, 7, "Cantidad", 1, 0, align="C")
    pdf.cell(45, 7, "Valor Unitario", 1, 0, align="R")
    pdf.cell(0, 7, "Subtotal", 1, 1, align="R")
    
    pdf.set_font("Helvetica", "", 9)
    
    if df_items is not None and not df_items.empty:
        for index, row in df_items.iterrows():
            desc = f"[{row.get('tipo_item', 'Item')}] {row.get('descripcion', '')}"
            if row.get('mecanico') and row['mecanico'] != '':
                desc += f" (Tec: {row['mecanico']})"
            
            # Cantidad (por defecto 1 si no existe)
            cantidad = row.get('cantidad', 1) if 'cantidad' in row else 1
            precio_unitario = float(row.get('precio_venta', 0)) / cantidad if cantidad > 0 else float(row.get('precio_venta', 0))
            subtotal = float(row.get('precio_venta', 0))
            
            # Descripción (truncada si es muy larga)
            desc_truncada = desc[:55]
            pdf.cell(110, 6, desc_truncada, 1, 0)
            pdf.cell(35, 6, f"{cantidad}", 1, 0, align="C")
            pdf.cell(45, 6, f"${precio_unitario:,.0f}".replace(",", "."), 1, 0, align="R")
            pdf.cell(0, 6, f"${subtotal:,.0f}".replace(",", "."), 1, 1, align="R")
    
    pdf.ln(2)
    
    # Totales
    pdf.set_font("Helvetica", "B", 10)
    
    if incluir_iva:
        # Cálculo de IVA (19% en Colombia)
        subtotal_sin_iva = total / 1.19
        iva = total - subtotal_sin_iva
        
        pdf.cell(190, 7, f"Subtotal: ${subtotal_sin_iva:,.0f}".replace(",", "."), 0, 1, align="R")
        pdf.cell(190, 7, f"IVA (19%): ${iva:,.0f}".replace(",", "."), 0, 1, align="R")
    
    pdf.cell(190, 8, f"TOTAL A PAGAR: ${total:,.0f}".replace(",", "."), 0, 1, align="R")
    
    pdf.ln(8)
    
    # Pie de página
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 4, "Gracias por confiar en nuestros servicios.", ln=True, align="C")
    pdf.cell(0, 4, "Conserve este documento para reclamar su vehículo.", ln=True, align="C")
    
    if estado and estado.lower() == "facturado":
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 4, "Documento válido para propósitos fiscales.", ln=True, align="C")
    
    return bytes(pdf.output())


def generar_pdf_orden(taller, hoja_id, fecha, cliente, nit, placa, estado, df_items, total):
    """
    Función legacy — mantiene compatibilidad con código existente.
    Llama a generar_pdf_orden_mejorado sin datos extras del taller.
    """
    return generar_pdf_orden_mejorado(
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
