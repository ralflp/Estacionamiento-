from django import forms
from .models import Person, Vehicle, AccessPermission, ControlDevice # ControlDevice es nuevo aquí

class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ['full_name', 'identifier']
        # Se podrían añadir widgets o personalizaciones aquí si fuera necesario
        # widgets = {
        #     'full_name': forms.TextInput(attrs={'class': 'form-control'}),
        #     'identifier': forms.TextInput(attrs={'class': 'form-control'}),
        # }

class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['owner', 'license_plate', 'description']
        # widgets = {
        #     'owner': forms.Select(attrs={'class': 'form-control'}),
        #     'license_plate': forms.TextInput(attrs={'class': 'form-control'}),
        #     'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        # }

class AccessPermissionForm(forms.ModelForm):
    class Meta:
        model = AccessPermission
        fields = ['person', 'access_point', 'is_active', 'valid_from', 'valid_until']
        widgets = {
            'valid_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'valid_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            # Se podrían añadir clases CSS a otros campos si se desea, como:
            # 'person': forms.Select(attrs={'class': 'form-control'}),
            # 'access_point': forms.Select(attrs={'class': 'form-control'}),
            # 'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hacer que los campos de fecha no sean obligatorios si blank=True en el modelo.
        # ModelForm debería manejar 'required' basado en 'blank=True' en el modelo,
        # pero esta personalización explícita puede ser útil para asegurar la consistencia
        # del atributo HTML 'required', especialmente con widgets como datetime-local.

        # El modelo AccessPermission tiene blank=True para valid_from y valid_until.
        # El atributo 'required' del campo del formulario se establece en False por defecto
        # por ModelForm cuando blank=True.
        # Sin embargo, si se quiere ser extra explícito o si el widget por defecto no se comporta
        # como se espera en todos los navegadores para el atributo 'required' visual,
        # se puede descomentar lo siguiente. Por ahora, confiamos en el comportamiento de ModelForm.
        #
        # if 'valid_from' in self.fields:
        #     self.fields['valid_from'].required = False
        # if 'valid_until' in self.fields:
        #     self.fields['valid_until'].required = False

        # Nota: El campo 'valid_from' tiene default=timezone.now en el modelo,
        # lo que significa que siempre tendrá un valor al crear una nueva instancia
        # a menos que se anule explícitamente. ModelForm lo pre-rellenará.
        # La lógica 'required=False' es más para permitir que el usuario borre
        # el campo en el formulario si eso es un caso de uso válido (y el modelo lo permite).
        # Dado que `default=timezone.now` está en el modelo para `valid_from`,
        # `required=False` para ese campo en el formulario significa que el usuario PUEDE borrarlo
        # y se guardará como None si no se proporciona otro valor y el modelo lo permite (null=True).
        pass # No se necesita personalización activa del __init__ por ahora.

class ControlDeviceForm(forms.ModelForm):
    class Meta:
        model = ControlDevice
        fields = [
            'name',
            'device_id',
            'access_point',
            'mqtt_topic',
            'ip_address',
            'is_active',
            'notes'
        ]
        # Ejemplo de widgets que podrían añadirse para mejorar la apariencia:
        # widgets = {
        #     'name': forms.TextInput(attrs={'class': 'form-control'}),
        #     'device_id': forms.TextInput(attrs={'class': 'form-control'}),
        #     'access_point': forms.Select(attrs={'class': 'form-control'}),
        #     'mqtt_topic': forms.TextInput(attrs={'class': 'form-control'}),
        #     'ip_address': forms.TextInput(attrs={'class': 'form-control'}), # IPInput sería más específico
        #     'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        #     'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        # }
