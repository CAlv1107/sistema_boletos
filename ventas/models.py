import uuid
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

class Rifa(models.Model):
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    cantidad_boletos = models.PositiveIntegerField(help_text="Ejemplo: 1000")
    precio_unid = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_sorteo = models.DateTimeField()

    def __str__(self):
        return self.titulo


class Producto(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    rifa_asociada = models.ForeignKey(Rifa, on_delete=models.SET_NULL, null=True, blank=True, related_name='productos_regalo', help_text="Asocia este artículo a un sorteo activo (Déjalo en blanco si es solo venta normal)")
    boletos_de_regalo = models.IntegerField(default=1, help_text="Cantidad de boletos que otorga la compra de este producto")
    stock = models.IntegerField(default=100)

    def __str__(self):
        asociacion = f" -> Rifa: {self.rifa_asociada.titulo}" if self.rifa_asociada else " (Venta Normal)"
        return f"{self.nombre} (${self.precio} MXN){asociacion}"


class CompraEfectuada(models.Model):
    ENTREGA_CHOICES = [
        ('fisico', 'Venta Física / Recolección'),
        ('domicilio', 'Envío a Domicilio'),
    ]

    nombre_comprador = models.CharField(max_length=200)
    whatsapp_comprador = models.CharField(max_length=20)
    email_comprador = models.EmailField()
    
    boletos_totales_ganados = models.IntegerField()
    boletos_ya_elegidos = models.IntegerField(default=0)
    
    token_seguro = models.CharField(max_length=64, unique=True) 
    fecha_pago = models.DateTimeField(auto_now_add=True)
    seleccion_completada = models.BooleanField(default=False)

    # NUEVOS CAMPOS CENTRALIZADOS EN LA COMPRA:
    tipo_entrega = models.CharField(
        max_length=20, 
        choices=ENTREGA_CHOICES, 
        default='fisico'
    )
    direccion = models.CharField(max_length=255, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    estado_republica = models.CharField(max_length=100, blank=True, null=True)
    codigo_postal = models.CharField(max_length=10, blank=True, null=True)
    referencias = models.TextField(blank=True, null=True)

    def boletos_restantes(self):
        return self.boletos_totales_ganados - self.boletos_ya_elegidos

    def __str__(self):
        return f"Compra #{self.id} - {self.nombre_comprador} ({self.tipo_entrega})"


class DetalleCompraProducto(models.Model):
    """ Registra exactamente qué productos y cuántas piezas adquirió el cliente en una compra """
    compra = models.ForeignKey(CompraEfectuada, on_delete=models.CASCADE, related_name='detalles_productos')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre} (Compra #{self.compra.id})"


class Boleto(models.Model):
    ESTADO_CHOICES = [
        ('disponible', 'Disponible'),
        ('apartado', 'Apartado Temporalmente'),
        ('vendido', 'Vendido'),
    ]
    
    # OPCIONES PARA TIPO DE ENTREGA (Mantenidas por compatibilidad)
    ENTREGA_CHOICES = [
        ('fisico', 'Venta Física / Recolección'),
        ('domicilio', 'Envío a Domicilio'),
    ]

    # NUEVA RELACIÓN: Vincula el boleto a la transacción principal
    compra = models.ForeignKey(
        CompraEfectuada, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='boletos'
    )

    rifa = models.ForeignKey(Rifa, on_delete=models.CASCADE, related_name='boletos')
    numero = models.PositiveIntegerField()
    disponible = models.BooleanField(default=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='disponible')
    propietario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    session_id = models.CharField(max_length=100, null=True, blank=True)
    
    # Datos de contacto en el boleto (para el sorteo)
    nombre_comprador = models.CharField(max_length=100, null=True, blank=True)
    whatsapp_comprador = models.CharField(max_length=20, null=True, blank=True)
    email_comprador = models.EmailField(null=True, blank=True)
    
    tipo_entrega = models.CharField(
        max_length=20, 
        choices=ENTREGA_CHOICES, 
        default='fisico'
    )
    codigo_verificacion = models.CharField(max_length=15, unique=True, null=True, blank=True)
    fecha_reserva = models.DateTimeField(null=True, blank=True)

    # Datos de entrega opcionales mantenidos por compatibilidad
    direccion = models.CharField(max_length=255, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    estado_republica = models.CharField(max_length=100, blank=True, null=True)
    codigo_postal = models.CharField(max_length=10, blank=True, null=True)
    referencias = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # Sincroniza datos del comprador desde la compra si está asociada
        if self.compra:
            if not self.nombre_comprador:
                self.nombre_comprador = self.compra.nombre_comprador
            if not self.whatsapp_comprador:
                self.whatsapp_comprador = self.compra.whatsapp_comprador
            if not self.email_comprador:
                self.email_comprador = self.compra.email_comprador
            if not self.tipo_entrega:
                self.tipo_entrega = self.compra.tipo_entrega

        # Genera código de verificación al vender el boleto
        if self.estado == 'vendido' and not self.codigo_verificacion:
            self.codigo_verificacion = str(uuid.uuid4()).split('-')[0].upper()
            
        super().save(*args, **kwargs)

    @property
    def reserva_expirada(self):
        if self.estado == 'apartado' and self.fecha_reserva:
            ahora = timezone.now()
            diferencia = ahora - self.fecha_reserva
            return diferencia.total_seconds() > 900
        return False

    def __str__(self):
        return f"{self.rifa.titulo} - No. {self.numero} ({self.estado})"


# --- LOGICA AUTOMATICA ---
@receiver(post_save, sender=Rifa)
def generar_boletos(sender, instance, created, **kwargs):
    if created:
        boletos = [
            Boleto(rifa=instance, numero=i) 
            for i in range(1, instance.cantidad_boletos + 1)
        ]
        Boleto.objects.bulk_create(boletos)