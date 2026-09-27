from django import forms

class DatosCompradorForm(forms.Form):
    nombre = forms.CharField(
        label="Nombre Completo",
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Juan Pérez', 'class': 'form-control'})
    )
    whatsapp = forms.CharField(
        label="WhatsApp",
        max_length=15,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. 5512345678', 'class': 'form-control'})
    )
    email = forms.EmailField(
        label="Correo Electrónico",
        widget=forms.EmailInput(attrs={'placeholder': 'tu@email.com', 'class': 'form-control'})
    )