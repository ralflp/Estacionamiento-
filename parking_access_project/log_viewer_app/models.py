from django.db import models
from django.utils import timezone
from django.conf import settings

# --- Default Tenant Logic ---
DEFAULT_TENANT_NAME = "Empresa Principal (Default)"
DEFAULT_TENANT_SUBDOMAIN = "default"

def get_default_tenant_pk():
    # Import Tenant model locally to avoid circular imports at startup if models are loaded out of order
    # or if this function is called by makemigrations before all apps are fully ready.
    from log_viewer_app.models import Tenant # Changed from .models for potentially wider applicability outside model file

    try:
        tenant = Tenant.objects.get(name=DEFAULT_TENANT_NAME)
        return tenant.pk
    except Tenant.DoesNotExist:
        try:
             tenant, created = Tenant.objects.get_or_create(
                name=DEFAULT_TENANT_NAME,
                defaults={'subdomain_prefix': DEFAULT_TENANT_SUBDOMAIN}
            )
             if created:
                 print(f"Warning: Default tenant '{DEFAULT_TENANT_NAME}' created by get_default_tenant_pk. This should ideally be handled by data migration 0016.")
             return tenant.pk
        except Exception as e:
            # This is a critical issue if it happens during a real 'migrate' operation
            # For 'makemigrations', Django might handle it or use a sentinel value if the app registry is not ready.
            # If this function is used as a default for a non-nullable field, returning None or raising error here will fail migrations.
            # A common practice for 'makemigrations' to succeed when it needs a default for a non-nullable FK
            # without querying the DB is to provide a temporary, simple default like an integer (e.g., 1)
            # and ensure that the data migration creates the default Tenant with that PK.
            # However, the previous migration should have made this robust.
            print(f"CRITICAL ERROR in get_default_tenant_pk: Default tenant '{DEFAULT_TENANT_NAME}' could not be fetched or created: {e}. This will likely cause issues.")
            # Raising an error might be better than returning a potentially incorrect PK like 1 if not coordinated.
            # For now, per instructions, we assume this setup should work due to prior data migration.
            # If makemigrations fails, this function might need to be simplified to return a literal for that phase.
            raise e # Re-raise the exception to make the problem visible


class Tenant(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True,
        help_text="Nombre de la empresa o inquilino"
    )
    subdomain_prefix = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="Prefijo de subdominio o identificador en URL (opcional, solo caracteres válidos para URL/DNS)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class AccessLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='access_logs', default=get_default_tenant_pk)
    timestamp = models.DateTimeField(auto_now_add=True)
    qr_data = models.CharField(max_length=255)
    access_granted = models.BooleanField()
    event_type = models.CharField(max_length=100, default="acceso_general")
    user_id = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] QR: {self.qr_data}, Acceso: {'Permitido' if self.access_granted else 'Denegado'}"

class Person(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='persons', default=get_default_tenant_pk)
    full_name = models.CharField(max_length=200, help_text="Nombre completo de la persona")
    identifier = models.CharField(max_length=100, help_text="Identificador único (e.g., DNI, ID de empleado)") # Removed unique=True
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='person_profile',
        help_text="Usuario del sistema Django asociado a esta persona (opcional)"
    )
    is_temporary_guest = models.BooleanField( # Nuevo campo
        default=False,
        help_text="Indica si esta persona es un invitado temporal"
    )
    registered_by = models.ForeignKey( # Nuevo campo
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registered_guests',
        help_text="Usuario o persona anfitriona que registró a este invitado (opcional)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('tenant', 'identifier'),)
        # Consider adding ordering if not already present and desired, e.g.
        # ordering = ['tenant', 'full_name']

    def __str__(self):
        guest_status = " (Invitado Temp.)" if self.is_temporary_guest else ""
        return f"{self.full_name} ({self.identifier}){guest_status}"

class Vehicle(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='vehicles', default=get_default_tenant_pk)
    owner = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='vehicles', help_text="Propietario del vehículo")
    license_plate = models.CharField(max_length=20, help_text="Placa o matrícula del vehículo") # Removed unique=True
    description = models.TextField(blank=True, help_text="Descripción adicional (e.g., color, modelo)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('tenant', 'license_plate'),)
        # Consider adding ordering if not already present and desired, e.g.
        # ordering = ['tenant', 'license_plate']

    def __str__(self):
        return f"{self.license_plate} ({self.owner.full_name})"

class AccessPoint(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='access_points', default=get_default_tenant_pk)
    name = models.CharField(max_length=100, help_text="Nombre o ID único del punto de acceso (e.g., 'Puerta Principal Garaje', 'Torno Entrada Este')") # Removed unique=True
    description = models.TextField(blank=True, help_text="Descripción adicional del punto de acceso")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('tenant', 'name'),)
        ordering = ['tenant', 'name']

    def __str__(self):
        return self.name

class AccessPermission(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='access_permissions', default=get_default_tenant_pk)
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
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='control_devices', default=get_default_tenant_pk)
    name = models.CharField(max_length=150, help_text="Nombre descriptivo para el dispositivo")
    device_id = models.CharField(max_length=100, help_text="Identificador único del dispositivo") # Removed unique=True
    access_point = models.ForeignKey(AccessPoint, on_delete=models.SET_NULL, null=True, blank=True, related_name='control_devices', help_text="Punto de acceso que este dispositivo controla")
    mqtt_topic = models.CharField(max_length=255, help_text="Tópico MQTT para enviar comandos")
    ip_address = models.GenericIPAddressField(protocol='both', blank=True, null=True, help_text="Dirección IP del dispositivo (opcional)")
    is_active = models.BooleanField(default=True, help_text="¿Está este dispositivo actualmente activo y operativo?")
    notes = models.TextField(blank=True, help_text="Notas adicionales")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('tenant', 'device_id'),)
        ordering = ['tenant', 'name']

    def __str__(self):
        ap_name = self.access_point.name if self.access_point else "No asignado"
        return f"{self.name} ({self.device_id}) - AP: {ap_name}"

class Service(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='services', default=get_default_tenant_pk)
    name = models.CharField(max_length=150, unique=True, help_text="Nombre del servicio o producto (e.g., 'Estacionamiento Mensual', 'Tarjeta de Acceso')")
    description = models.TextField(blank=True, null=True, help_text="Descripción detallada del servicio")
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio base del servicio")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"{self.name} - ${self.price:.2f}"

class UserSubscription(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='user_subscriptions', default=get_default_tenant_pk)
    BILLING_CYCLE_CHOICES = [('once', 'Pago Único'), ('monthly', 'Mensual'), ('quarterly', 'Trimestral'), ('annually', 'Anual'), ('other', 'Otro')]
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='subscriptions', help_text="Persona asociada a esta suscripción")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='subscriptions', help_text="Servicio al que está suscrita la persona")
    start_date = models.DateField(default=timezone.now, help_text="Fecha de inicio de la suscripción")
    end_date = models.DateField(null=True, blank=True, help_text="Fecha de fin de la suscripción (opcional)")
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='monthly', help_text="Ciclo de facturación")
    billing_cycle_anchor_day = models.PositiveSmallIntegerField(
        null=True, blank=True, default=1,
        help_text="Día del mes para el anclaje de facturación (e.g., 1, 15, 28). Usado para determinar cuándo generar la factura en ciclos periódicos."
    )
    price_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Precio especial para esta suscripción")
    is_active = models.BooleanField(default=True, help_text="Indica si esta suscripción está actualmente activa")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-start_date', 'person__full_name']
    def get_effective_price(self):
        if self.price_override is not None: return self.price_override
        return self.service.price
    def __str__(self):
        status = "Activa" if self.is_active else "Inactiva"; price_info = self.get_effective_price()
        end_date_str = self.end_date.strftime('%Y-%m-%d') if self.end_date else "Indefinida"
        return f"Suscripción de {self.person.full_name} a {self.service.name} ({status}) - ${price_info:.2f} ({self.get_billing_cycle_display()}). Fin: {end_date_str}"

class Invoice(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='invoices', default=get_default_tenant_pk)
    STATUS_CHOICES = [('draft', 'Borrador'), ('pending', 'Pendiente'), ('paid', 'Pagada'), ('overdue', 'Vencida'), ('cancelled', 'Cancelada'), ('partial', 'Parcialmente Pagada')]
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name='invoices', help_text="Persona a la que se emite la factura")
    user_subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices', help_text="Suscripción asociada a esta factura (opcional)")
    invoice_number = models.CharField(max_length=50, unique=True, help_text="Número de factura único")
    cycle_start_date = models.DateField(null=True, blank=True, help_text="Fecha de inicio del ciclo de facturación que cubre esta factura")
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, help_text="Monto total a pagar")
    due_date = models.DateField(help_text="Fecha de vencimiento para el pago")
    paid_date = models.DateField(null=True, blank=True, help_text="Fecha en que se completó el pago (opcional)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', help_text="Estado actual de la factura")
    notes = models.TextField(blank=True, null=True, help_text="Notas o comentarios adicionales (opcional)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-due_date', 'person__full_name']
    def __str__(self):
        return f"Factura {self.invoice_number} para {self.person.full_name} - ${self.amount_due:.2f} (Estado: {self.get_status_display()})"

class Payment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=False, related_name='payments', default=get_default_tenant_pk)
    person = models.ForeignKey(Person, on_delete=models.SET_NULL, null=True, blank=False, related_name='payments', help_text="Persona que realizó el pago")
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_made', help_text="Factura a la que se aplica este pago (opcional)")
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
        invoice_info = f" para Factura {self.invoice.invoice_number}" if self.invoice else ""
        return f"Pago de {self.amount:.2f} por {person_name} el {self.payment_date.strftime('%Y-%m-%d %H:%M')}{invoice_info}"
