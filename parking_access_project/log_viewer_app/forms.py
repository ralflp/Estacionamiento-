from django import forms
from .models import Person, Vehicle, AccessPermission, ControlDevice, AccessPoint # AccessPoint importado
# from django.forms.fields import DateTimeField # No es necesario, forms.DateTimeField es suficiente

class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ['full_name', 'identifier', 'user', 'is_temporary_guest', 'registered_by'] # Campos actualizados de Person
        # Considerar widgets si se quiere personalizar la apariencia, e.g., para el campo 'user'
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control custom-select'}), # Ejemplo
        }
        # O excluir campos si no deben ser editables directamente aquí:
        # exclude = ['registered_by'] # si registered_by se asigna automáticamente en la vista

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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'valid_from' in self.fields:
            self.fields['valid_from'].required = False
        if 'valid_until' in self.fields:
            self.fields['valid_until'].required = False

class ControlDeviceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

        if tenant:
            self.fields['access_point'].queryset = AccessPoint.objects.filter(tenant=tenant).order_by('name')
        elif self.instance and self.instance.pk and hasattr(self.instance, 'tenant') and self.instance.tenant:
            # If editing an instance and tenant was not explicitly passed,
            # filter by the instance's current tenant.
            self.fields['access_point'].queryset = AccessPoint.objects.filter(tenant=self.instance.tenant).order_by('name')
        else:
            # No tenant context, show no access points to prevent incorrect assignment.
            # This might happen in Django admin if not customized to pass tenant,
            # or if the form is instantiated somewhere without tenant context.
            self.fields['access_point'].queryset = AccessPoint.objects.none()

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

class GuestRegistrationForm(forms.Form):
    guest_full_name = forms.CharField(label="Nombre completo del invitado", max_length=200)
    guest_identifier = forms.CharField(label="Identificador del invitado (e.g., DNI, email)", max_length=100)

    access_point = forms.ModelChoiceField(
        queryset=AccessPoint.objects.all().order_by('name'),
        label="Punto de Acceso a conceder"
    )
    permission_valid_from = forms.DateTimeField(
        label="Permiso válido desde",
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        help_text="Fecha y hora de inicio del permiso."
    )
    permission_valid_until = forms.DateTimeField(
        label="Permiso válido hasta",
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        help_text="Fecha y hora de fin del permiso."
    )

    def clean_guest_identifier(self):
        identifier = self.cleaned_data.get('guest_identifier')
        if Person.objects.filter(identifier=identifier).exists():
            # Podríamos ser más específicos: si es un invitado temporal activo, o un usuario permanente.
            # Por ahora, cualquier identificador existente es un conflicto para un nuevo invitado.
            raise forms.ValidationError("Ya existe una persona (empleado o invitado) con este identificador.")
        return identifier

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('permission_valid_from')
        valid_until = cleaned_data.get('permission_valid_until')

        if valid_from and valid_until and valid_until <= valid_from:
            self.add_error('permission_valid_until',
                           "La fecha 'válido hasta' debe ser posterior a la fecha 'válido desde'.")

        # Validar que la fecha de inicio no sea en el pasado (opcional, pero buena práctica)
        # from django.utils import timezone
        # if valid_from and valid_from < timezone.now():
        #     self.add_error('permission_valid_from', "La fecha de inicio del permiso no puede ser en el pasado.")

        return cleaned_data

class PersonProfileEditForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ['full_name']
        # widgets = {
        #     'full_name': forms.TextInput(attrs={'class': 'form-control-special'}), # Ejemplo si se necesita clase especial
        # }
        labels = {
            'full_name': "Nombre Completo", # Etiqueta más amigable
        }
        help_texts = {
            'full_name': "Así es como tu nombre se mostrará en el sistema.",
        }

class AccessPointForm(forms.ModelForm):
    class Meta:
        model = AccessPoint
        fields = ['name', 'description']
        labels = {
            'name': "Nombre del Punto de Acceso",
            'description': "Descripción Adicional (opcional)",
        }
        help_texts = {
            'name': "Identificador único para este punto de acceso dentro de la empresa (e.g., 'Puerta Principal Garaje').",
            'description': "Detalles como ubicación, tipo de puerta/barrera, etc.",
        }
        # widgets = {
        #     'name': forms.TextInput(attrs={'class': 'form-control'}),
        #     'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        # }
