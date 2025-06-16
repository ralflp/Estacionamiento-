from django.contrib import admin, messages # messages es nuevo aquí
from .models import ( # Importación agrupada
    AccessLog, Person, Vehicle, AccessPoint,
    AccessPermission, ControlDevice, Payment
)
from .utils import process_payment_for_access # Importar la función de procesamiento

# Register your models here.

# Simple registrations
if not admin.site.is_registered(AccessLog):
    admin.site.register(AccessLog)
if not admin.site.is_registered(Person):
    admin.site.register(Person)
if not admin.site.is_registered(Vehicle):
    admin.site.register(Vehicle)
if not admin.site.is_registered(AccessPoint):
    admin.site.register(AccessPoint)
if not admin.site.is_registered(AccessPermission):
    admin.site.register(AccessPermission)


# Clase ModelAdmin personalizada para ControlDevice (ya existente)
@admin.register(ControlDevice)
class ControlDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'device_id', 'access_point', 'mqtt_topic', 'is_active', 'ip_address')
    list_filter = ('is_active', 'access_point__name')
    search_fields = ('name', 'device_id', 'mqtt_topic', 'access_point__name', 'ip_address')
    list_editable = ('is_active', 'mqtt_topic')

    fieldsets = (
        (None, {
            'fields': ('name', 'device_id', 'is_active')
        }),
        ('Asignación y Configuración MQTT', {
            'fields': ('access_point', 'mqtt_topic')
        }),
        ('Información Adicional (Opcional)', {
            'fields': ('ip_address', 'notes', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('created_at', 'updated_at')

# Clase ModelAdmin personalizada para Payment (nueva)
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'person',
        'amount',
        'payment_date',
        'payment_method',
        'reference_number',
        'processed_for_access',
        'created_at'
    )
    list_filter = ('payment_method', 'processed_for_access', 'payment_date', 'person__full_name')
    search_fields = ('person__full_name', 'person__identifier', 'reference_number', 'amount')
    list_editable = ('processed_for_access',)
    date_hierarchy = 'payment_date'

    fieldsets = (
        (None, {
            'fields': ('person', 'amount', 'payment_date', 'payment_method')
        }),
        ('Detalles Adicionales', {
            'fields': ('reference_number', 'notes')
        }),
        ('Estado de Procesamiento', {
            'fields': ('processed_for_access',)
        }),
        ('Auditoría', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        })
    )
    readonly_fields = ('created_at', 'updated_at')

    actions = ['process_selected_payments_action'] # Nombre de la acción

    def process_selected_payments_action(self, request, queryset):
        processed_count = 0
        already_processed_count = 0
        failed_count = 0

        for payment in queryset:
            # Chequeo explícito antes de llamar a la función para mensaje más claro al admin
            if payment.processed_for_access:
                already_processed_count +=1
                continue # No llamar a process_payment_for_access si ya estaba procesado

            success = process_payment_for_access(payment) # Llama a la función de utils
            if success:
                processed_count += 1
            else:
                # La función process_payment_for_access ya loguea los detalles del error.
                failed_count +=1

        if processed_count > 0:
            self.message_user(request,
                              f"{processed_count} pago(s) procesado(s) exitosamente para activar/extender acceso.",
                              messages.SUCCESS)
        if already_processed_count > 0:
             self.message_user(request,
                              f"{already_processed_count} pago(s) ya habían sido procesados anteriormente y fueron omitidos.",
                              messages.INFO) # Cambiado a INFO para diferenciarlo de un éxito nuevo
        if failed_count > 0:
            self.message_user(request,
                              f"{failed_count} pago(s) no pudieron ser procesados. Revise los logs del sistema para más detalles.",
                              messages.ERROR)

    process_selected_payments_action.short_description = "Procesar Pagos para Activar/Extender Acceso"
