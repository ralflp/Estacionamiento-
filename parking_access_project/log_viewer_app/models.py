from django.db import models
from django.utils import timezone # Para valores por defecto de fechas

class AccessLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    qr_data = models.CharField(max_length=255)
    access_granted = models.BooleanField()
    event_type = models.CharField(max_length=100, default="acceso_general")
    user_id = models.CharField(max_length=100, null=True, blank=True) # Could eventually be a ForeignKey to Person or User

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] QR: {self.qr_data}, Acceso: {'Permitido' if self.access_granted else 'Denegado'}"

class Person(models.Model):
    full_name = models.CharField(max_length=200, help_text="Nombre completo de la persona")
    identifier = models.CharField(max_length=100, unique=True, help_text="Identificador único (e.g., DNI, ID de empleado)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name} ({self.identifier})"

class Vehicle(models.Model):
    owner = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='vehicles', help_text="Propietario del vehículo")
    license_plate = models.CharField(max_length=20, unique=True, help_text="Placa o matrícula del vehículo")
    description = models.TextField(blank=True, help_text="Descripción adicional (e.g., color, modelo)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.license_plate} ({self.owner.full_name})"

class AccessPoint(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="Nombre o ID único del punto de acceso (e.g., 'Puerta Principal Garaje', 'Torno Entrada Este')")
    description = models.TextField(blank=True, help_text="Descripción adicional del punto de acceso")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class AccessPermission(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='permissions', help_text="Persona a la que se concede el permiso")
    access_point = models.ForeignKey(AccessPoint, on_delete=models.CASCADE, related_name='permissions', help_text="Punto de acceso para el cual se concede el permiso")
    is_active = models.BooleanField(default=True, help_text="¿Está este permiso actualmente activo?")
    # Campos opcionales para validez temporal del permiso:
    valid_from = models.DateTimeField(null=True, blank=True, default=timezone.now, help_text="Fecha y hora desde la cual el permiso es válido (opcional)")
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora hasta la cual el permiso es válido (opcional, dejar en blanco para 'sin caducidad')")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Asegurar que una persona solo tenga un registro de permiso por punto de acceso.
        # Si se quieren múltiples periodos o condiciones, se necesitaría un enfoque más complejo.
        unique_together = ('person', 'access_point')

    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        validity = ""
        if self.valid_from:
            validity += f" Desde: {self.valid_from.strftime('%Y-%m-%d %H:%M')}"
        if self.valid_until:
            validity += f" Hasta: {self.valid_until.strftime('%Y-%m-%d %H:%M')}"
        if not validity and self.valid_from : # If only valid_from is set (due to default=timezone.now)
             validity = " Siempre (desde creación)" # Or adjust based on how you interpret only valid_from
        elif not validity:
            validity = " Siempre"


        return f"Permiso para {self.person.full_name} en {self.access_point.name} ({status},{validity})"
