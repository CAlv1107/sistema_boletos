from django.urls import path
from . import views

urlpatterns = [
    path('', views.tienda_inicio, {'rifa_id': 1}, name='inicio'),
    path('rifa/<int:rifa_id>/', views.detalle_rifa, name='detalle_rifa'),

    path('rifa/seleccion/<str:token>/', views.elegir_boletos_post_pago, name='elegir_boletos_post_pago'),
    
    # NUEVA: Ruta para la pantalla de confirmación final que llama elegir_boletos_post_pago
    path('confirmacion-final/<str:token>/', views.confirmacion_final, name='confirmacion_final'),

    # NUEVA: Ruta para procesar la selección de boletos vía AJAX
    path('confirmar-seleccion/', views.confirmar_seleccion, name='confirmar_seleccion'),
    path('carrito/agregar/', views.agregar_producto_al_carrito, name='agregar_producto_al_carrito'),
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('pago-exitoso/', views.pago_exitoso, name='pago_exitoso'),
    path('pago-error/', views.pago_error, name='pago_error'),
    path('carrito/eliminar/<int:producto_id>/', views.eliminar_del_carrito, name='eliminar_del_carrito'),
    path('checkout-paypal/', views.checkout_paypal, name='checkout_paypal'),
]