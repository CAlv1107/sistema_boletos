def contador_carrito(request):
    """
    Calcula el total de artículos en el carrito almacenado en la sesión.
    """
    total_items = 0
    # Obtenemos el carrito de la sesión (o un diccionario vacío si no existe)
    carrito = request.session.get('carrito', {})
    
    if isinstance(carrito, dict):
        # Si el carrito es una estructura de diccionario {producto_id: {'cantidad': X, ...}}
        for item in carrito.values():
            if isinstance(item, dict):
                total_items += item.get('cantidad', 1)
            else:
                # Si es un diccionario simple {producto_id: cantidad}
                total_items += int(item)
    elif isinstance(carrito, list):
        total_items = len(carrito)

    # Imprime en la consola del servidor para verificar si está detectando los items
    # (Puedes quitar este print una vez que funcione)
    print(f"DEBUG CARRITO: Contenido de sesión = {carrito} | Total items = {total_items}")

    return {'total_items_carrito': total_items}