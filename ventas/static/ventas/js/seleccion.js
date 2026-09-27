let boletosElegidos = [];

function seleccionarBoleto(elemento) {
    // Si el boleto ya está vendido, no hacemos nada
    if (elemento.classList.contains('vendido')) {
        return;
    }

    const numero = elemento.getAttribute('data-numero');

    // Toggle de la clase 'seleccionado' para el cambio de color (Azul)
    if (elemento.classList.contains('seleccionado')) {
        elemento.classList.remove('seleccionado');
        boletosElegidos = boletosElegidos.filter(n => n !== numero);
    } else {
        elemento.classList.add('seleccionado');
        boletosElegidos.push(numero);
    }

    actualizarResumen();
}

function actualizarResumen() {
    const resumenDiv = document.getElementById('resumen-seleccion');
    const spanNumeros = document.getElementById('numeros-seleccionados');

    if (boletosElegidos.length > 0) {
        // Usamos 'flex' para que los elementos internos se alineen bien
        resumenDiv.style.display = 'flex';
        
        // Ordenamos numéricamente para que se vea limpio
        const listaOrdenada = [...boletosElegidos].sort((a, b) => parseInt(a) - parseInt(b));
        spanNumeros.innerText = listaOrdenada.join(', ');
        
        // Efecto opcional: Scroll automático al panel si es la primera vez que aparece
        if (boletosElegidos.length === 1) {
            resumenDiv.classList.add('animate-up');
        }
    } else {
        resumenDiv.style.display = 'none';
    }
}

function enviarSeleccion() {
    const btnContinuar = document.getElementById('btn-continuar');
    const idRifaInput = document.getElementById('rifa-id');
    const csrfElement = document.querySelector('[name=csrfmiddlewaretoken]');

    if (!idRifaInput || !csrfElement) {
        console.error("Faltan elementos críticos en el HTML (ID Rifa o CSRF)");
        return;
    }

    if (boletosElegidos.length === 0) {
        alert("Por favor, selecciona al menos un boleto.");
        return;
    }

    // Deshabilitamos el botón para evitar múltiples clics
    btnContinuar.disabled = true;
    btnContinuar.innerText = "Procesando...";

    const datos = {
        boletos: boletosElegidos, 
        rifa_id: idRifaInput.value
    };

    fetch('/confirmar-seleccion/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfElement.value
        },
        body: JSON.stringify(datos)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'ok') {
            window.location.href = '/carrito/';
        } else {
            alert('Error: ' + data.mensaje);
            // Re-habilitamos si hay error para que el usuario intente de nuevo
            btnContinuar.disabled = false;
            btnContinuar.innerText = "Confirmar y Pagar";
        }
    })
    .catch(error => {
        console.error('Error:', error);
        btnContinuar.disabled = false;
        btnContinuar.innerText = "Confirmar y Pagar";
    });
}

// Detectamos cuando la página termina de cargar
document.addEventListener('DOMContentLoaded', function() {
    // 1. Buscamos todos los elementos que Django pintó con la clase 'seleccionado'
    const preSeleccionados = document.querySelectorAll('.boleto.seleccionado');
    
    preSeleccionados.forEach(elemento => {
        const numero = elemento.getAttribute('data-numero');
        
        // 2. Si el número no está en nuestro array, lo agregamos
        if (!boletosElegidos.includes(numero)) {
            boletosElegidos.push(numero);
        }
    });

    // 3. Actualizamos el resumen para que el botón de "Confirmar" aparezca de inmediato
    actualizarResumen();
});