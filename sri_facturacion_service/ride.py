"""
Arma el RIDE (Representación Impresa del Documento Electrónico) — el PDF
"legible por humanos" del comprobante. Mismo layout que el original
(sales_project/facturacion_electronica/ride.py), pero lee todo desde
`comprobante.payload` (el pedido original, guardado tal cual llegó) en vez
de un `Invoice` de Django — así este servicio nunca necesita conocer el
modelo de factura de ningún proyecto cliente, alcanza con lo que ya se
guardó al crear el comprobante (ver services.py).

OJO: este sistema no soporta ICE/IRBPNR/subsidio de combustibles ni líneas
exentas o no objeto de IVA — esas filas del desglose siempre se muestran en
$0.00 (son honestas: reflejan que el sistema no las calcula, no que la
factura real las tenga). Todo el subtotal de la factura va bajo la única
tarifa de IVA que mandó el cliente en el payload.
"""
import io
from decimal import Decimal


def _build_barcode_image(clave_acceso):
    """Code128 (no EAN13: la clave de acceso tiene 49 dígitos, no 12/13)."""
    import barcode
    from barcode.writer import ImageWriter

    buffer = io.BytesIO()
    code128 = barcode.get('code128', clave_acceso, writer=ImageWriter())
    code128.write(buffer, options={'write_text': False, 'module_height': 10})
    buffer.seek(0)
    return buffer.read()


def _box(story_rows, width, padding=4, border_color=None):
    """Envuelve una lista de Paragraphs/Flowables en una tabla de 1 columna
    con borde — es el recuadro con marco que usa el RIDE oficial tanto para
    los datos del emisor como para los del comprobante/autorización."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    color = border_color or colors.HexColor('#334155')
    table = Table([[row] for row in story_rows], colWidths=[width])
    table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, color),
        ('LEFTPADDING', (0, 0), (-1, -1), padding),
        ('RIGHTPADDING', (0, 0), (-1, -1), padding),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return table


def build_ride_pdf(comprobante):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from xml_builder import DESCRIPCION_FORMA_PAGO_SRI

    payload = comprobante.payload
    emisor = payload['emisor']
    comprador = payload['comprador']
    forma_pago = payload['forma_pago']

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=1.2 * cm, bottomMargin=1.2 * cm, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    ancho_util = doc.width
    normal = ParagraphStyle('normal', parent=styles['Normal'], fontSize=8, textColor=colors.black, leading=10)
    bold = ParagraphStyle('bold', parent=normal, fontName='Helvetica-Bold')
    small = ParagraphStyle('small', parent=normal, fontSize=7, leading=9)
    factura_title = ParagraphStyle('factura_title', parent=normal, fontSize=13, fontName='Helvetica-Bold', alignment=1)
    logo_placeholder = ParagraphStyle('logo_placeholder', parent=normal, fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#dc2626'))

    if comprobante.ambiente == comprobante.AMBIENTE_PRUEBAS:
        aviso_pruebas = ParagraphStyle('aviso', parent=normal, fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#dc2626'), alignment=1)
        story.append(Paragraph('AMBIENTE DE PRUEBAS — SIN VALIDEZ TRIBUTARIA', aviso_pruebas))
        story.append(Spacer(1, 0.2 * cm))

    # ---------- Cabecera: recuadro del emisor + recuadro del comprobante ----------

    izquierda_ancho = ancho_util * 0.48
    derecha_ancho = ancho_util * 0.48

    emisor_rows = [Paragraph('NO TIENE LOGO', logo_placeholder), Spacer(1, 0.15 * cm)]
    emisor_rows.append(Paragraph(emisor['razon_social'], bold))
    if emisor.get('nombre_comercial'):
        emisor_rows.append(Paragraph(emisor['nombre_comercial'], normal))
    direccion = emisor.get('direccion_matriz') or 'S/N'
    emisor_rows.append(Paragraph(f'<b>Dirección Matriz:</b> {direccion}', small))
    emisor_rows.append(Paragraph(f'<b>Dirección Sucursal:</b> {direccion}', small))
    emisor_rows.append(Paragraph(
        f'<b>OBLIGADO A LLEVAR CONTABILIDAD:</b> {"SI" if emisor.get("obligado_contabilidad") else "NO"}', small
    ))
    caja_emisor = _box(emisor_rows, izquierda_ancho)

    numero_autorizacion = comprobante.numero_autorizacion or comprobante.clave_acceso
    fecha_autorizacion = (
        f'{comprobante.fecha_autorizacion:%d/%m/%Y %H:%M:%S}' if comprobante.fecha_autorizacion else '-'
    )
    barcode_bytes = None
    try:
        barcode_bytes = _build_barcode_image(comprobante.clave_acceso)
    except Exception:
        # El barcode es un extra visual — si por lo que sea no se puede
        # generar (dato inesperado), el PDF igual debe verse con la clave
        # de acceso en texto (ya se agrega abajo).
        pass

    comprobante_rows = [
        Paragraph(f'<b>R.U.C.:</b> {emisor.get("ruc") or "-"}', normal),
        Paragraph('FACTURA', factura_title),
        Paragraph(f'<b>No.</b> {comprobante.establecimiento}-{comprobante.punto_emision}-{comprobante.secuencial}', normal),
        Spacer(1, 0.1 * cm),
        Paragraph('<b>NÚMERO DE AUTORIZACIÓN</b>', small),
        Paragraph(numero_autorizacion, small),
        Paragraph(f'<b>FECHA Y HORA DE AUTORIZACIÓN:</b> {fecha_autorizacion}', small),
        Paragraph(f'<b>AMBIENTE:</b> {comprobante.ambiente_display().upper()}', small),
        Paragraph('<b>EMISIÓN:</b> NORMAL', small),
        Spacer(1, 0.1 * cm),
        Paragraph('<b>CLAVE DE ACCESO</b>', small),
    ]
    if barcode_bytes:
        comprobante_rows.append(Image(io.BytesIO(barcode_bytes), width=izquierda_ancho - 0.6 * cm, height=1.6 * cm))
    comprobante_rows.append(Paragraph(comprobante.clave_acceso, small))
    caja_comprobante = _box(comprobante_rows, derecha_ancho)

    header_table = Table([[caja_emisor, caja_comprobante]], colWidths=[izquierda_ancho, derecha_ancho])
    header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(header_table)
    story.append(Spacer(1, 0.3 * cm))

    # ---------- Datos del comprador ----------

    if comprador.get('es_consumidor_final'):
        razon_social = 'CONSUMIDOR FINAL'
        identificacion = '9999999999999'
    else:
        razon_social = comprador['razon_social']
        identificacion = comprador['identificacion']

    comprador_rows = [
        [Paragraph(f'<b>Razón Social / Nombres y Apellidos:</b> {razon_social}', small), '', ''],
        [Paragraph(f'<b>Identificación:</b> {identificacion}', small),
         Paragraph(f'<b>Fecha:</b> {payload["fecha_emision_ddmmyyyy"]}', small),
         Paragraph('<b>Placa/Matrícula:</b>', small)],
        [Paragraph(f'<b>Dirección:</b> {comprador.get("direccion") or "-"}', small), '', Paragraph('<b>Guía:</b>', small)],
    ]
    comprador_table = Table(comprador_rows, colWidths=[ancho_util * 0.55, ancho_util * 0.25, ancho_util * 0.20])
    comprador_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#334155')),
        ('SPAN', (0, 0), (-1, 0)),
        ('SPAN', (0, 2), (1, 2)),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(comprador_table)
    story.append(Spacer(1, 0.3 * cm))

    # ---------- Detalle de líneas ----------

    header_cell = ParagraphStyle('header_cell', parent=small, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
    celda = ParagraphStyle('celda', parent=small, alignment=1)
    celda_izq = ParagraphStyle('celda_izq', parent=small, alignment=0)

    encabezados = [
        Paragraph('Cod.<br/>Principal', header_cell), Paragraph('Cod.<br/>Auxiliar', header_cell),
        Paragraph('Cantidad', header_cell), Paragraph('Descripción', header_cell),
        Paragraph('Detalle<br/>Adicional', header_cell), Paragraph('Precio<br/>Unitario', header_cell),
        Paragraph('Subsidio', header_cell), Paragraph('Precio sin<br/>Subsidio', header_cell),
        Paragraph('Descuento', header_cell), Paragraph('Precio<br/>Total', header_cell),
    ]
    filas = [encabezados]
    for linea in payload['lineas']:
        cantidad = Decimal(str(linea['cantidad']))
        precio_unitario = Decimal(str(linea['precio_unitario']))
        subtotal_linea = (cantidad * precio_unitario).quantize(Decimal('0.01'))
        filas.append([
            Paragraph(str(linea['codigo']), celda),
            Paragraph(linea.get('codigo_barras') or '-', celda),
            Paragraph(f'{cantidad:.2f}', celda),
            Paragraph(linea['descripcion'], celda_izq),
            Paragraph('-', celda),
            Paragraph(f'{precio_unitario:.2f}', celda),
            Paragraph('0.00', celda),
            Paragraph(f'{precio_unitario:.2f}', celda),
            Paragraph('0.00', celda),
            Paragraph(f'{subtotal_linea:.2f}', celda),
        ])
    anchos_cols = [c * cm for c in (1.3, 1.6, 1.1, 3.5, 2.2, 1.6, 1.3, 1.7, 1.3, 1.4)]
    detalle_table = Table(filas, colWidths=anchos_cols, repeatRows=1)
    detalle_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4e54c8')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94a3b8')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(detalle_table)
    story.append(Spacer(1, 0.3 * cm))

    # ---------- Información adicional + forma de pago (izq) / totales (der) ----------

    info_adicional_rows = [Paragraph('<b>Información Adicional</b>', bold)]
    if comprador.get('email'):
        info_adicional_rows.append(Paragraph(f'email: {comprador["email"]}', small))
    if comprador.get('telefono'):
        info_adicional_rows.append(Paragraph(f'teléfono: {comprador["telefono"]}', small))
    if len(info_adicional_rows) == 1:
        info_adicional_rows.append(Paragraph('-', small))

    codigo_pago = forma_pago.get('codigo_sri', '01')
    descripcion_pago = DESCRIPCION_FORMA_PAGO_SRI.get(codigo_pago, '')
    monto_pago = Decimal(str(forma_pago['monto_a_pagar'])) if forma_pago.get('es_credito') else Decimal(str(payload['total']))
    forma_pago_table = Table(
        [
            [Paragraph('<b>Forma de pago</b>', small), Paragraph('<b>Valor</b>', small)],
            [Paragraph(f'{codigo_pago} - {descripcion_pago}', small), Paragraph(f'{monto_pago:.2f}', small)],
        ],
        colWidths=[ancho_util * 0.48 * 0.7, ancho_util * 0.48 * 0.3],
    )
    forma_pago_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94a3b8')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    izquierda_inferior = Table(
        [[row] for row in info_adicional_rows] + [[forma_pago_table]],
        colWidths=[ancho_util * 0.48],
    )
    izquierda_inferior.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#334155')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    # El sistema no soporta ICE/IRBPNR/subsidio de combustibles ni líneas
    # exentas o no objeto de IVA — se muestran en 0.00 (no se inventan
    # valores: es honesto reflejar que el sistema no los calcula).
    porcentaje_iva = Decimal(str(payload['iva_porcentaje']))
    subtotal = Decimal(str(payload['subtotal']))
    iva_valor = Decimal(str(payload['iva_valor']))
    total = Decimal(str(payload['total']))
    totales_data = [
        [f'SUBTOTAL {porcentaje_iva:.0f}%', f'{subtotal:.2f}'],
        ['SUBTOTAL NO OBJETO DE IVA', '0.00'],
        ['SUBTOTAL EXENTO DE IVA', '0.00'],
        ['SUBTOTAL SIN IMPUESTOS', f'{subtotal:.2f}'],
        ['TOTAL DESCUENTO', '0.00'],
        ['ICE', '0.00'],
        [f'IVA {porcentaje_iva:.0f}%', f'{iva_valor:.2f}'],
        ['IRBPNR', '0.00'],
        ['PROPINA', '0.00'],
        ['VALOR TOTAL', f'{total:.2f}'],
    ]
    totales_table = Table(
        [[Paragraph(f'<font size=7>{label}</font>', celda_izq), Paragraph(f'<font size=7>{valor}</font>', celda)] for label, valor in totales_data],
        colWidths=[ancho_util * 0.48 * 0.65, ancho_util * 0.48 * 0.35],
    )
    totales_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94a3b8')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]))
    subsidio_data = [
        ['VALOR TOTAL SIN SUBSIDIO', '0.00'],
        ['AHORRO POR SUBSIDIO (incluye IVA cuando corresponda)', '0.00'],
    ]
    subsidio_table = Table(
        [[Paragraph(f'<font size=6.5>{label}</font>', celda_izq), Paragraph(f'<font size=6.5>{valor}</font>', celda)] for label, valor in subsidio_data],
        colWidths=[ancho_util * 0.48 * 0.65, ancho_util * 0.48 * 0.35],
    )
    subsidio_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94a3b8')),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]))
    derecha_inferior = Table(
        [[totales_table], [Spacer(1, 0.15 * cm)], [subsidio_table]],
        colWidths=[ancho_util * 0.48],
    )

    inferior_table = Table(
        [[izquierda_inferior, derecha_inferior]],
        colWidths=[ancho_util * 0.5, ancho_util * 0.5],
    )
    inferior_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(inferior_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
