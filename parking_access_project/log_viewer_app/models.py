from django.db import models
from django.utils import timezone # Para valores por defecto de fechas
# from django.conf import settings # No es necesario para este modelo específico

class AccessLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    qr_data = models.CharField(max_length=255)
    access_granted = models.BooleanField()
    event_type = models.CharField(max_length=100, default="acceso_general")
    user_id = models.CharField(max_length=100, null=True, blank=True)

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
    valid_from = models.DateTimeField(null=True, blank=True, default=timezone.now, help_text="Fecha y hora desde la cual el permiso es válido (opcional)")
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora hasta la cual el permiso es válido (opcional, dejar en blanco para 'sin caducidad')")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = ('person', 'access_point')
    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        validity = ""
        if self.valid_from: validity += f" Desde: {self.valid_from.strftime('%Y-%m-%d %H:%M')}"
        if self.valid_until: validity += f" Hasta: {self.valid_until.strftime('%Y-%m-%d %H:%M')}"
        if not validity and self.valid_from : validity = " Siempre (desde creación)"
        elif not validity: validity = " Siempre"
        return f"Permiso para {self.person.full_name} en {self.access_point.name} ({status},{validity})"

class ControlDevice(models.Model):
    name = models.CharField(max_length=150, help_text="Nombre descriptivo para el dispositivo")
    device_id = models.CharField(max_length=100, unique=True, help_text="Identificador único del dispositivo")
    access_point = models.ForeignKey(AccessPoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='control_devices', help_text="Punto de acceso que este dispositivo controla")
    mqtt_topic = models.CharField(max_length=255, help_text="Tópico MQTT para enviar comandos")
    ip_address = models.GenericIPAddressField(protocol='both', blank=True, null=True, help_text="Dirección IP del dispositivo (opcional)")
    is_active = models.BooleanField(default=True, help_text="¿Está este dispositivo actualmente activo y operativo?")
    notes = models.TextField(blank=True, help_text="Notas adicionales")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        ap_name = self.access_point.name if self.access_point else "No asignado"
        return f"{self.name} ({self.device_id}) - AP: {ap_name}"

class Payment(models.Model):
    person = models.ForeignKey(Person, on_delete=models.SET_NULL, null=True, blank=False, related_name='payments', help_text="Persona que realizó el pago")
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Monto del pago")
    payment_date = models.DateTimeField(default=timezone.now, help_text="Fecha y hora en que se registró el pago")
    payment_method = models.CharField(max_length=50, default="efectivo", choices=[('efectivo', 'Efectivo'), ('tarjeta_credito', 'Tarjeta de Crédito'), ('tarjeta_debito', 'Tarjeta de Débito'), ('transferencia', 'Transferencia Bancaria'), ('paypal', 'PayPal'), ('otro', 'Otro')], help_text="Método de pago utilizado")
    reference_number = models.CharField(max_length=100, blank=True, null=True, help_text="Número de referencia o ID de transacción (opcional)")
    notes = models.TextField(blank=True, null=True, help_text="Notas adicionales sobre el pago (opcional)")
    processed_for_access = models.BooleanField(default=False, help_text="Indica si este pago ya ha sido procesado para activar/extender un acceso")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        person_name = self.person.full_name if self.person else "N/A"
        return f"Pago de {self.amount:.2f} por {person_name} el {self.payment_date.strftime('%Y-%m-%d %H:%M')}"
