from django.contrib import admin
from .models import Rifa, Boleto, Producto, CompraEfectuada, DetalleCompraProducto
from django.utils.html import format_html
from django.utils import timezone

# --- INLINES PARA GESTIONAR LA COMPRA EN UN SOLO LUGAR ---

class DetalleCompraInline(admin.TabularInline):
    model = DetalleCompraProducto
    extra = 0
    fields = ('producto', 'cantidad', 'precio_unitario')
    readonly_fields = ('producto', 'cantidad', 'precio_unitario')
    can_delete = False


class BoletoInline(admin.TabularInline):
    model = Boleto
    extra = 0
    fields = ('numero', 'rifa', 'estado')
    readonly_fields = ('numero', 'rifa', 'estado')
    can_delete = False


# --- GESTIÓN DE COMPRAS Y ENVÍOS ---

@admin.register(CompraEfectuada)
class CompraEfectuadaAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'nombre_comprador', 
        'whatsapp_comprador', 
        'alerta_envio', 
        'resumen_productos', 
        'boletos_asignados', 
        'direccion_envio_corta', 
        'fecha_pago'
    )
    
    list_filter = ('tipo_entrega', 'seleccion_completada', 'fecha_pago')
    
    search_fields = (
        'nombre_comprador', 
        'email_comprador', 
        'whatsapp_comprador', 
        'direccion', 
        'ciudad', 
        'estado_republica', 
        'token_seguro'
    )
    
    inlines = [DetalleCompraInline, BoletoInline]

    # Alerta visual de Envío a Domicilio o Entrega Física
    def alerta_envio(self, obj):
        tipo = (obj.tipo_entrega or '').lower()
        if tipo == 'domicilio':
            return format_html(
                '<span style="background-color: {}; color: white; padding: 4px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">{}</span>',
                '#dc3545',
                '📦 REQUIERE ENVÍO'
            )
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">{}</span>',
            '#17a2b8',
            '🏪 ENTREGA FÍSICA'
        )
    alerta_envio.short_description = 'Tipo Entrega'

    # Resumen de productos comprados (ej. 1x Gorra, 2x Llavero)
    def resumen_productos(self, obj):
        detalles = obj.detalles_productos.all()
        if detalles:
            return ", ".join([f"{item.cantidad}x {item.producto.nombre}" for item in detalles])
        return "Sin productos registrados"
    resumen_productos.short_description = 'Productos Adquiridos'

    # Muestra los boletos que le corresponden
    def boletos_asignados(self, obj):
        boletos = obj.boletos.all()
        if boletos:
            numeros = [f"#{b.numero:03d}" for b in boletos]
            return f"{len(numeros)} boleto(s): {', '.join(numeros)}"
        return "Pendientes de elegir"
    boletos_asignados.short_description = 'Boletos Regalados'

    # Dirección resumida de envío
    def direccion_envio_corta(self, obj):
        if obj.tipo_entrega == 'domicilio' and obj.direccion:
            ubicacion = f"{obj.ciudad}, {obj.estado_republica}" if obj.estado_republica else (obj.ciudad or '')
            cp = f" (CP: {obj.codigo_postal})" if obj.codigo_postal else ""
            return f"{obj.direccion}, {ubicacion}{cp}"
        return "-"
    direccion_envio_corta.short_description = 'Dirección de Envío'


# --- GESTIÓN DE RIFAS Y BOLETOS ---

@admin.register(Rifa)
class RifaAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'cantidad_boletos', 'precio_unid', 'fecha_sorteo')
    search_fields = ('titulo',)


@admin.register(Boleto)
class BoletoAdmin(admin.ModelAdmin):
    list_display = (
        'numero', 
        'rifa', 
        'color_estado', 
        'get_nombre_comprador',
        'get_whatsapp_comprador',
        'get_email_comprador',
        'timer_apartado', 
        'session_id_corto'
    )
    
    list_filter = ('estado', 'tipo_entrega', 'rifa', 'disponible')
    
    search_fields = (
        'numero', 
        'nombre_comprador', 
        'email_comprador', 
        'whatsapp_comprador',
        'compra__nombre_comprador',
        'compra__whatsapp_comprador',
        'compra__email_comprador',
        'session_id'
    )
    
    actions = ['marcar_como_vendido']

    def marcar_como_vendido(self, request, queryset):
        queryset.update(estado='vendido', disponible=False, session_id=None)
    marcar_como_vendido.short_description = "Marcar seleccionados como VENDIDOS"

    # Visualización estética del estado
    def color_estado(self, obj):
        colores = {
            'disponible': '#28a745',
            'apartado': '#ffc107',
            'vendido': '#6c757d',
        }
        bg = colores.get(obj.estado, '#000000')
        texto = obj.get_estado_display().upper()
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 10px; font-weight: bold; font-size: 11px;">{}</span>',
            bg,
            texto
        )
    color_estado.short_description = 'Estado'

    # Datos del Comprador para el Sorteo
    def get_nombre_comprador(self, obj):
        return obj.nombre_comprador or (obj.compra.nombre_comprador if obj.compra else "-")
    get_nombre_comprador.short_description = 'Titular del Boleto'

    def get_whatsapp_comprador(self, obj):
        return obj.whatsapp_comprador or (obj.compra.whatsapp_comprador if obj.compra else "-")
    get_whatsapp_comprador.short_description = 'WhatsApp'

    def get_email_comprador(self, obj):
        return obj.email_comprador or (obj.compra.email_comprador if obj.compra else "-")
    get_email_comprador.short_description = 'Correo'

    # Monitor del tiempo de reserva
    def timer_apartado(self, obj):
        if obj.estado == 'apartado' and obj.fecha_reserva:
            expiracion = obj.fecha_reserva + timezone.timedelta(minutes=15)
            ahora = timezone.now()
            if expiracion > ahora:
                diff = expiracion - ahora
                minutos = int(diff.total_seconds() // 60)
                segundos = int(diff.total_seconds() % 60)
                return f"Libera en {minutos}m {segundos}s"
            return 'EXPIRADO'
        return "-"
    timer_apartado.short_description = 'Tiempo Reserva'

    # ID de sesión simplificado
    def session_id_corto(self, obj):
        if obj.session_id:
            return f"{obj.session_id[:10]}..."
        return "N/A"
    session_id_corto.short_description = 'Sesión'


# --- GESTIÓN DE PRODUCTOS ---

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio', 'stock', 'ver_imagen_miniatura')
    search_fields = ('nombre',)
    list_filter = ('stock',)

    def ver_imagen_miniatura(self, obj):
        if obj.imagen:
            return format_html('<img src="{}" style="width: 50px; height: auto; border-radius: 5px;" />', obj.imagen.url)
        return "Sin imagen"
    ver_imagen_miniatura.short_description = 'Miniatura'