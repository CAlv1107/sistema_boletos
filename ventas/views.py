from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
import json
from django.utils import timezone
from datetime import timedelta
from .models import Rifa, Boleto, Producto, CompraEfectuada, DetalleCompraProducto
from .forms import DatosCompradorForm 
from django.db.models import Q, F
from django.views.decorators.cache import never_cache
from django.contrib import messages
import qrcode
from io import BytesIO
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from email.mime.image import MIMEImage
from django.conf import settings
import secrets
from django.db import transaction


# ==========================================
# 1. TIENDA Y DETALLE
# ==========================================
@never_cache
def tienda_inicio(request, rifa_id=1):
    """ Muestra la lista de productos disponibles para comprar y participar """
    liberar_boletos_expirados()
    productos = Producto.objects.filter(stock__gt=0)
    return render(request, 'ventas/tienda.html', {'productos': productos})


def detalle_rifa(request, rifa_id):
    """ Muestra la cuadrícula de boletos de una rifa específica """
    rifa = get_object_or_404(Rifa, id=rifa_id)
    boletos = Boleto.objects.filter(rifa=rifa).order_by('numero')
    return render(request, 'ventas/detalle_rifa.html', {'rifa': rifa, 'boletos': boletos})


# =======================================================
# 2. CARRITO Y SELECCIÓN DE PRODUCTOS
# =======================================================
def agregar_producto_al_carrito(request):
    """ Guarda el producto en la sesión y calcula cuántos boletos de regalo acumula """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            producto_id = data.get('producto_id')
            
            producto = get_object_or_404(Producto, id=producto_id)
            carrito = request.session.get('carrito_productos', {})
            
            prod_id_str = str(producto_id)
            carrito[prod_id_str] = carrito.get(prod_id_str, 0) + 1
            request.session['carrito_productos'] = carrito
            
            boletos_totales_derecho = 0
            for p_id, cantidad in carrito.items():
                p_obj = Producto.objects.get(id=p_id)
                boletos_totales_derecho += (p_obj.boletos_de_regalo * cantidad)
            
            request.session['boletos_por_elegir'] = boletos_totales_derecho
            
            return JsonResponse({
                'status': 'ok', 
                'mensaje': f'¡{producto.nombre} añadido! Llevas {boletos_totales_derecho} boletos de regalo acumulados.'
            })
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'mensaje': str(e)}, status=400)
            
    return JsonResponse({'status': 'error', 'mensaje': 'Método no permitido'}, status=405)


def ver_carrito(request):
    """ Muestra los productos del carrito, calcula el total a pagar, acumula boletos y procesa datos de contacto y entrega """
    liberar_boletos_expirados()
    carrito = request.session.get('carrito_productos', {})
    items_carrito = []
    total_compra = 0
    boletos_totales = 0

    # 1. Recuperamos productos de la BD y calculamos subtotales y boletos
    for p_id, cantidad in carrito.items():
        try:
            producto = Producto.objects.get(id=p_id)
            subtotal = producto.precio * cantidad
            total_compra += subtotal
            
            boletos_producto = 0
            if producto.rifa_asociada:
                boletos_producto = producto.boletos_de_regalo * cantidad
                boletos_totales += boletos_producto

            items_carrito.append({
                'producto': producto,
                'cantidad': cantidad,
                'subtotal': subtotal,
                'boletos_ganados': boletos_producto
            })
        except Producto.DoesNotExist:
            continue

    # 2. Si el usuario guarda sus datos de contacto y entrega
    if request.method == 'POST':
        request.session['comprador_nombre'] = request.POST.get('nombre', '').strip()
        request.session['comprador_whatsapp'] = request.POST.get('whatsapp', '').strip()
        request.session['comprador_email'] = request.POST.get('email', '').strip()
        
        # Guardado de datos de envío en sesión
        tipo_entrega = request.POST.get('tipo_entrega', 'fisico').strip()
        request.session['tipo_entrega'] = tipo_entrega

        if tipo_entrega == 'domicilio':
            request.session['direccion'] = request.POST.get('calle', '').strip() or request.POST.get('direccion', '').strip()
            request.session['ciudad'] = request.POST.get('ciudad', '').strip()
            request.session['estado_republica'] = request.POST.get('estado_republica', '').strip()
            request.session['codigo_postal'] = request.POST.get('cp', '').strip() or request.POST.get('codigo_postal', '').strip()
            request.session['referencias'] = request.POST.get('referencias', '').strip()
        else:
            # Limpiar datos de envío si se selecciona entrega física/presencial
            request.session['direccion'] = ''
            request.session['ciudad'] = ''
            request.session['estado_republica'] = ''
            request.session['codigo_postal'] = ''
            request.session['referencias'] = ''
        
        messages.success(request, "Datos de contacto y envío guardados correctamente.")

        # REDIRECCIÓN A LA PANTALLA DE CHECKOUT PAYPAL
        return redirect('checkout_paypal')

    segundos_restantes = request.session.get('reserva_expiracion_segundos', 0)
    
    context = {
        'items_carrito': items_carrito,
        'total_compra': total_compra,
        'boletos_totales': boletos_totales,
        'segundos_restantes': segundos_restantes,
        'comprador_nombre': request.session.get('comprador_nombre', ''),
        'comprador_whatsapp': request.session.get('comprador_whatsapp', ''),
        'comprador_email': request.session.get('comprador_email', ''),
        'tipo_entrega': request.session.get('tipo_entrega', ''),
        'direccion': request.session.get('direccion', ''),
        'ciudad': request.session.get('ciudad', ''),
        'estado_republica': request.session.get('estado_republica', ''),
        'codigo_postal': request.session.get('codigo_postal', ''),
        'referencias': request.session.get('referencias', ''),
    }
    
    return render(request, 'ventas/carrito.html', context)


def eliminar_del_carrito(request, producto_id):
    """ Elimina un producto específico del carrito de la sesión """
    carrito = request.session.get('carrito_productos', {})
    str_id = str(producto_id)
    
    if str_id in carrito:
        del carrito[str_id]
        request.session['carrito_productos'] = carrito
        messages.warning(request, "Producto eliminado del carrito.")
        
    return redirect('ver_carrito')


# ==========================================
# 3. CONTROL DE TIEMPO
# ==========================================
def liberar_boletos_expirados():
    limite = timezone.now() - timezone.timedelta(minutes=15)
    
    boletos_a_liberar = Boleto.objects.filter(
        estado='apartado', 
        fecha_reserva__lt=limite
    )
    
    boletos_a_liberar.update(
        estado='disponible', 
        fecha_reserva=None, 
        session_id=None,
        disponible=True
    )


# =======================================================
# 4. PROCESAMIENTO DE PAGO Y CORREO CON QR
# =======================================================
def enviar_correo_con_qr(boleto):
    qr_data = f"Boleto: {boleto.numero} | Rifa: {boleto.rifa.titulo} | Comprador: {boleto.nombre_comprador or (boleto.compra.nombre_comprador if boleto.compra else '')}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_image_png = buffer.getvalue()

    nombre_comprador = boleto.nombre_comprador or (boleto.compra.nombre_comprador if boleto.compra else "Cliente")
    email_comprador = boleto.email_comprador or (boleto.compra.email_comprador if boleto.compra else "")

    context = {
        'nombre': nombre_comprador,
        'nombre_sorteo': boleto.rifa.titulo,
        'numero_boleto': boleto.numero,
        'transaccion_id': getattr(boleto, 'id', 'N/A'),
        'fecha': timezone.now().strftime('%d/%m/%Y %H:%M')
    }
    
    html_content = render_to_string('ventas/email_boleto.html', context)
    msg = EmailMultiAlternatives(
        subject=f"Confirmación de Boleto #{boleto.numero}",
        body=f"Hola {nombre_comprador}, tu boleto es el #{boleto.numero}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_comprador]
    )
    msg.attach_alternative(html_content, "text/html")

    email_qr = MIMEImage(qr_image_png)
    email_qr.add_header('Content-ID', '<qrcode_img>')
    msg.attach(email_qr)
    msg.send()


@transaction.atomic
def pago_exitoso(request):
    """ PayPal aprueba el cobro. Registra la compra, guarda detalles de productos, descuenta inventario y redirige """
    carrito = request.session.get('carrito_productos', {})
    
    if not carrito:
        messages.error(request, "Tu carrito está vacío.")
        return redirect('tienda_inicio')

    nombre = request.session.get('comprador_nombre', 'Cliente Temporal')
    whatsapp = request.session.get('comprador_whatsapp', '0000000000')
    email = request.session.get('comprador_email', 'correo@temporal.com')

    tipo_entrega = request.session.get('tipo_entrega', 'fisico')
    direccion = request.session.get('direccion', '')
    ciudad = request.session.get('ciudad', '')
    estado_republica = request.session.get('estado_republica', '')
    codigo_postal = request.session.get('codigo_postal', '')
    referencias = request.session.get('referencias', '')

    boletos_totales_ganados = 0
    rifa_destino = None
    monto_total_compra = 0

    # 1. Crear el objeto principal CompraEfectuada
    token_unico = secrets.token_urlsafe(32)
    compra = CompraEfectuada.objects.create(
        nombre_comprador=nombre,
        whatsapp_comprador=whatsapp,
        email_comprador=email,
        tipo_entrega=tipo_entrega,
        direccion=direccion,
        ciudad=ciudad,
        estado_republica=estado_republica,
        codigo_postal=codigo_postal,
        referencias=referencias,
        boletos_totales_ganados=0,  # Se actualizará tras revisar productos
        boletos_ya_elegidos=0,
        token_seguro=token_unico,
        seleccion_completada=False,
        fecha_pago=timezone.now()
    )

    # 2. Guardar los artículos comprados y actualizar stock
    for p_id, cantidad in carrito.items():
        try:
            producto = Producto.objects.select_for_update().get(id=p_id)
            subtotal = producto.precio * cantidad
            monto_total_compra += subtotal

            # Crear detalle de compra
            DetalleCompraProducto.objects.create(
                compra=compra,
                producto=producto,
                cantidad=cantidad,
                precio_unitario=producto.precio
            )

            # Descontar stock
            producto.stock = F('stock') - cantidad
            producto.save()

            if producto.rifa_asociada:
                boletos_totales_ganados += (producto.boletos_de_regalo * cantidad)
                rifa_destino = producto.rifa_asociada

        except Producto.DoesNotExist:
            continue

    # Actualizar monto total y boletos ganados en la compra
    compra.monto_total = monto_total_compra
    compra.boletos_totales_ganados = boletos_totales_ganados
    compra.save()

    # Limpiamos el carrito de la sesión
    request.session['carrito_productos'] = {}
    if 'boletos_por_elegir' in request.session:
        del request.session['boletos_por_elegir']

    if boletos_totales_ganados > 0 and rifa_destino:
        return redirect('elegir_boletos_post_pago', token=token_unico)
    else:
        compra.seleccion_completada = True
        compra.save()
        return render(request, 'ventas/gracias_por_tu_compra.html', {'compra': compra})


def pago_error(request):
    return render(request, 'ventas/pago_error.html')


def confirmar_seleccion(request):
    return JsonResponse({'status': 'ok', 'message': 'Listo para programar la lógica'})


# ==========================================
# VISTA CHECKOUT PAYPAL
# ==========================================
@never_cache
def checkout_paypal(request):
    """ Muestra la pantalla de pago seguro con los botones de PayPal """
    carrito = request.session.get('carrito_productos', {})
    
    if not carrito:
        messages.warning(request, "Tu carrito está vacío. Agrega productos antes de pagar.")
        return redirect('ver_carrito')

    total = 0
    boletos_totales = 0

    for p_id, cantidad in carrito.items():
        try:
            producto = Producto.objects.get(id=p_id)
            total += producto.precio * cantidad
            if producto.rifa_asociada:
                boletos_totales += producto.boletos_de_regalo * cantidad
        except Producto.DoesNotExist:
            continue

    context = {
        'total': total,
        'boletos_totales': boletos_totales,
        'segundos_restantes': request.session.get('reserva_expiracion_segundos', 900),
        'comprador_nombre': request.session.get('comprador_nombre', ''),
        'comprador_email': request.session.get('comprador_email', ''),
    }
    
    return render(request, 'ventas/checkout_paypal.html', context)


# =======================================================
# 5. ELECCIÓN DE BOLETOS POST-PAGO Y CONFIRMACIÓN
# =======================================================

def enviar_correo_confirmacion(compra, boletos):
    """ Envía un correo electrónico con formato HTML elegante (Negro y Dorado) """
    
    numeros_list = [f"#{str(b.numero).zfill(3)}" for b in boletos]
    
    boletos_html = "".join([
        f'<span style="display: inline-block; background-color: #FFD700; color: #000000; font-weight: bold; padding: 10px 20px; margin: 6px; border-radius: 6px; font-size: 18px; border: 1px solid #FFFFFF;">'
        f'<b style="color: #000000; font-size: 18px;">{num}</b></span>'
        for num in numeros_list
    ])

    detalles_envio_html = ""
    if compra.tipo_entrega:
        detalles_envio_html = f"""
        <tr>
            <td style="padding: 8px 0; border-bottom: 1px solid #2a2a2a;">Tipo de Entrega:</td>
            <td align="right" style="padding: 8px 0; border-bottom: 1px solid #2a2a2a; color: #ffffff; font-weight: bold; text-transform: capitalize;">{compra.tipo_entrega}</td>
        </tr>
        """
        
        if compra.tipo_entrega.lower() == 'domicilio' and compra.direccion:
            ubicacion = f"{compra.ciudad}, {compra.estado_republica}" if compra.estado_republica else compra.ciudad
            
            detalles_envio_html += f"""
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #2a2a2a;">Dirección:</td>
                <td align="right" style="padding: 8px 0; border-bottom: 1px solid #2a2a2a; color: #ffffff; font-weight: bold;">
                    {compra.direccion}, {ubicacion} (CP: {compra.codigo_postal})
                </td>
            </tr>
            """
            
            if compra.referencias:
                detalles_envio_html += f"""
                <tr>
                    <td style="padding: 8px 0; border-bottom: 1px solid #2a2a2a;">Referencias:</td>
                    <td align="right" style="padding: 8px 0; border-bottom: 1px solid #2a2a2a; color: #ffffff; font-weight: bold;">{compra.referencias}</td>
                </tr>
                """
    
    asunto = f"🎟️ ¡Confirmación de tus boletos para el Gran Sorteo!"
    
    mensaje_texto = f"""
    Hola {compra.nombre_comprador},

    ¡Gracias por tu compra! Tu selección de boletos se ha completado con éxito.

    Boletos asignados: {', '.join(numeros_list)}
    Total de boletos: {len(boletos)}

    ¡Mucho éxito en el sorteo!
    Tu Truck n Car
    """
    
    html_message = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
    </head>
    <body style="margin: 0; padding: 0; background-color: #0f0f0f; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #ffffff;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #0f0f0f; padding: 40px 10px;">
            <tr>
                <td align="center">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #1a1a1a; border: 1px solid #333333; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                        
                        <!-- Encabezado -->
                        <tr>
                            <td align="center" style="background: linear-gradient(180deg, #222222 0%, #111111 100%); padding: 30px 20px; border-bottom: 2px solid #D4AF37;">
                                <h1 style="color: #FFD700; margin: 0; font-size: 26px; text-transform: uppercase; letter-spacing: 2px; font-weight: 800;">
                                    Tu truck n car
                                </h1>
                                <p style="color: #aaaaaa; margin: 5px 0 0 0; font-size: 13px; letter-spacing: 1px; text-transform: uppercase;">
                                    Confirmación de Participación
                                </p>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding: 30px 30px 20px 30px;">
                                <h2 style="color: #ffffff; margin-top: 0; font-size: 20px;">
                                    ¡Hola, <span style="color: #FFD700;">{compra.nombre_comprador}</span>! 👋
                                </h2>
                                <p style="color: #cccccc; font-size: 15px; line-height: 1.6; margin-bottom: 25px;">
                                    ¡Gracias por participar! Tu selección de boletos se ha registrado exitosamente. A continuación encuentras los detalles de tus números asignados:
                                </p>
                                
                                <!-- Caja de Boletos -->
                                <div style="background-color: #111111; border: 1px solid #333333; border-radius: 8px; padding: 20px; text-align: center; margin-bottom: 25px;">
                                    <p style="color: #888888; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-top: 0; margin-bottom: 12px;">
                                        Tus boletos asignados ({len(boletos)})
                                    </p>
                                    <div>
                                        {boletos_html}
                                    </div>
                                </div>

                                <!-- Resumen de compra -->
                                <table width="100%" style="border-collapse: collapse; font-size: 14px; color: #cccccc; margin-bottom: 25px;">
                                    <tr>
                                        <td style="padding: 8px 0; border-bottom: 1px solid #2a2a2a;">Comprador:</td>
                                        <td align="right" style="padding: 8px 0; border-bottom: 1px solid #2a2a2a; color: #ffffff; font-weight: bold;">{compra.nombre_comprador}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 8px 0; border-bottom: 1px solid #2a2a2a;">WhatsApp:</td>
                                        <td align="right" style="padding: 8px 0; border-bottom: 1px solid #2a2a2a; color: #ffffff; font-weight: bold;">{compra.whatsapp_comprador}</td>
                                    </tr>
                                    {detalles_envio_html}
                                    <tr>
                                        <td style="padding: 8px 0; border-bottom: 1px solid #2a2a2a;">Total Boletos:</td>
                                        <td align="right" style="padding: 8px 0; border-bottom: 1px solid #2a2a2a; color: #FFD700; font-weight: bold;">{len(boletos)}</td>
                                    </tr>
                                </table>

                                <p style="color: #cccccc; font-size: 14px; line-height: 1.6; text-align: center; margin-top: 30px;">
                                    ¡Te deseamos el mayor de los éxitos en el próximo sorteo! 🍀
                                </p>
                            </td>
                        </tr>

                        <!-- Pie de página -->
                        <tr>
                            <td align="center" style="background-color: #111111; padding: 20px; border-top: 1px solid #222222; color: #666666; font-size: 12px;">
                                <p style="margin: 0 0 5px 0;">Este es un correo automático de confirmación.</p>
                                <p style="margin: 0; color: #888888;">© Tu Truck n Car. Todos los derechos reservados.</p>
                            </td>
                        </tr>

                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    send_mail(
        subject=asunto,
        message=mensaje_texto,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[compra.email_comprador],
        html_message=html_message,
        fail_silently=False,
    )

@never_cache
def elegir_boletos_post_pago(request, token):
    """ Pantalla donde el usuario ve la cuadrícula y elige sus números ganados """
    compra = get_object_or_404(CompraEfectuada, token_seguro=token, seleccion_completada=False)
    
    expiracion = compra.fecha_pago + timedelta(minutes=15)
    ahora = timezone.now()
    
    # 1. Validación de tiempo
    if ahora > expiracion:
        asignar_boletos_automaticos_por_tiempo(compra)
        return redirect('confirmacion_final', token=token)

    segundos_restantes = max(0, int((expiracion - ahora).total_seconds()))
    
    rifa = Rifa.objects.first() 
    boletos_disponibles = Boleto.objects.filter(rifa=rifa, estado='disponible').order_by('numero')

    # 2. Procesamiento de la elección mediante AJAX (POST)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            numeros_elegidos = data.get('boletos', [])
            
            if len(numeros_elegidos) != compra.boletos_restantes():
                return JsonResponse({'status': 'error', 'mensaje': f'Debes seleccionar exactamente {compra.boletos_restantes()} boletos.'})

            boletos_validos = list(Boleto.objects.filter(rifa=rifa, numero__in=numeros_elegidos, estado='disponible'))
            
            if len(boletos_validos) == len(numeros_elegidos):
                for boleto in boletos_validos:
                    boleto.estado = 'vendido'
                    boleto.disponible = False
                    boleto.compra = compra  # Enlace directo al modelo CompraEfectuada
                    
                    # Copia de seguridad de datos de comprador
                    boleto.nombre_comprador = compra.nombre_comprador
                    boleto.whatsapp_comprador = compra.whatsapp_comprador
                    boleto.email_comprador = compra.email_comprador
                    
                    # Copia de seguridad de datos de entrega
                    boleto.tipo_entrega = compra.tipo_entrega
                    boleto.direccion = compra.direccion
                    boleto.ciudad = compra.ciudad
                    boleto.estado_republica = compra.estado_republica
                    boleto.codigo_postal = compra.codigo_postal
                    boleto.referencias = compra.referencias
                    
                    boleto.save()

                compra.boletos_ya_elegidos = compra.boletos_totales_ganados
                compra.seleccion_completada = True
                compra.save()

                # ENVIAR UN SOLO CORREO CON TODOS LOS BOLETOS
                try:
                    enviar_correo_confirmacion(compra, boletos_validos)
                except Exception as e:
                    print(f"Error al enviar correo: {e}")

                return JsonResponse({'status': 'ok', 'redirect_url': f'/confirmacion-final/{token}/'})
            else:
                return JsonResponse({'status': 'error', 'mensaje': 'Uno o más números fueron ganados por otra persona justo ahora. Elige otros.'})
                
        except Exception as e:
            return JsonResponse({'status': 'error', 'mensaje': str(e)}, status=400)

    # 3. Contexto para la plantilla
    context = {
        'compra': compra,
        'rifa': rifa,
        'boletos': boletos_disponibles,
        'segundos_restantes': segundos_restantes,
        'modo_post_pago': True,
        'boletos_por_elegir': compra.boletos_restantes()
    }

    return render(request, 'ventas/detalle_rifa.html', context)


def asignar_boletos_automaticos_por_tiempo(compra):
    rifa = Rifa.objects.first()
    boletos_al_azar = list(Boleto.objects.filter(rifa=rifa, estado='disponible')[:compra.boletos_restantes()])
    
    for boleto in boletos_al_azar:
        boleto.estado = 'vendido'
        boleto.disponible = False
        boleto.compra = compra
        
        # Copia de datos al boleto
        boleto.nombre_comprador = compra.nombre_comprador
        boleto.whatsapp_comprador = compra.whatsapp_comprador
        boleto.email_comprador = compra.email_comprador
        
        boleto.tipo_entrega = compra.tipo_entrega
        boleto.direccion = compra.direccion
        boleto.ciudad = compra.ciudad
        boleto.estado_republica = compra.estado_republica 
        boleto.codigo_postal = compra.codigo_postal
        boleto.referencias = compra.referencias
        
        boleto.save()
            
    compra.boletos_ya_elegidos = compra.boletos_totales_ganados
    compra.seleccion_completada = True
    compra.save()

    try:
        enviar_correo_confirmacion(compra, boletos_al_azar)
    except Exception as e:
        print(f"Error al enviar correo en asignación automática: {e}")


def confirmacion_final(request, token):
    """ Pantalla final que agradece al usuario y muestra sus boletos ganados """
    compra = get_object_or_404(CompraEfectuada, token_seguro=token)
    rifa = Rifa.objects.first()
    
    # Obtenemos los boletos vinculados a esta compra
    boletos_adquiridos = Boleto.objects.filter(compra=compra).order_by('numero')

    context = {
        'compra': compra,
        'rifa': rifa,
        'boletos': boletos_adquiridos,
    }
    
    return render(request, 'ventas/confirmacion_final.html', context)