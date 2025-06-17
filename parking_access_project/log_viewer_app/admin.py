from django.contrib import admin, messages
from .models import (
    Tenant, # Added Tenant import
    AccessLog, Person, Vehicle, AccessPoint,
    AccessPermission, ControlDevice, Payment,
    Service, UserSubscription, Invoice
)
from .utils import process_payment_for_access
from .billing_utils import get_due_cycle_start_date_for_subscription, generate_invoice_for_subscription
from django.utils import timezone
from rest_framework.authtoken.models import Token
import logging

logger = logging.getLogger(__name__)

# Register Tenant Admin
@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'subdomain_prefix', 'created_at', 'updated_at')
    search_fields = ('name', 'subdomain_prefix')
    readonly_fields = ('created_at', 'updated_at')

# Unregister models that were simply registered to redefine with ModelAdmin
# This is to ensure we don't try to register them twice if the simple registration lines are still present.
# Alternatively, ensure the simple registration lines are removed. For this overwrite, they will be implicitly removed.

@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'qr_data', 'access_granted', 'event_type', 'user_id', 'tenant')
    list_filter = ('timestamp', 'access_granted', 'event_type', 'tenant')
    search_fields = ('qr_data', 'user_id', 'event_type', 'tenant__name')
    readonly_fields = ('timestamp',)
    # No fieldsets specified, so all fields will be shown including tenant.
    # Add 'tenant' to autocomplete_fields if appropriate, but might not be for AccessLog.

@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'identifier', 'tenant', 'user', 'is_temporary_guest', 'created_at')
    list_filter = ('tenant', 'is_temporary_guest', 'created_at', 'updated_at')
    search_fields = ('full_name', 'identifier', 'user__username', 'tenant__name')
    autocomplete_fields = ['user', 'registered_by', 'tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'full_name', 'identifier')}),
        ('Asociación de Usuario', {'fields': ('user',)}),
        ('Info de Invitado', {'fields': ('is_temporary_guest', 'registered_by')}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('license_plate', 'owner', 'tenant', 'description', 'created_at')
    list_filter = ('tenant', 'owner__full_name')
    search_fields = ('license_plate', 'owner__full_name', 'owner__identifier', 'tenant__name')
    autocomplete_fields = ['owner', 'tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'owner', 'license_plate', 'description')}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(AccessPoint)
class AccessPointAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'description', 'created_at')
    list_filter = ('tenant', 'created_at')
    search_fields = ('name', 'description', 'tenant__name')
    autocomplete_fields = ['tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'name', 'description')}),
        ('Auditoría', {'fields': ('created_at',), 'classes': ('collapse',)}) # updated_at not on model
    )
    readonly_fields = ('created_at',)


@admin.register(AccessPermission)
class AccessPermissionAdmin(admin.ModelAdmin):
    list_display = ('person', 'access_point', 'tenant', 'is_active', 'valid_from', 'valid_until')
    list_filter = ('tenant', 'is_active', 'access_point__name', 'person__full_name')
    search_fields = ('person__full_name', 'access_point__name', 'tenant__name')
    autocomplete_fields = ['person', 'access_point', 'tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'person', 'access_point', 'is_active')}),
        ('Validez', {'fields': ('valid_from', 'valid_until')}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'tenant', 'created_at', 'updated_at')
    list_filter = ('tenant', 'price')
    search_fields = ('name', 'description', 'tenant__name')
    autocomplete_fields = ['tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'name', 'price', 'description')}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('person', 'service', 'tenant', 'start_date', 'end_date', 'billing_cycle', 'get_effective_price', 'is_active')
    list_filter = ('tenant', 'is_active', 'billing_cycle', 'service__name', 'person__full_name')
    search_fields = ('person__full_name', 'person__identifier', 'service__name', 'tenant__name')
    list_editable = ('is_active', 'end_date')
    autocomplete_fields = ['person', 'service', 'tenant']
    date_hierarchy = 'start_date'
    fieldsets = (
        (None, {'fields': ('tenant', 'person', 'service', 'is_active')}),
        ('Detalles de Suscripción', {'fields': ('start_date', 'end_date', 'billing_cycle', 'billing_cycle_anchor_day', 'price_override')}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')
    actions = ['generate_invoices_for_selected_action']

    def generate_invoices_for_selected_action(self, request, queryset):
        today = timezone.now().date()
        newly_generated_count = 0
        already_existed_count = 0
        skipped_or_failed_count = 0
        processed_subscriptions = 0

        for subscription in queryset:
            processed_subscriptions += 1
            if not subscription.is_active:
                skipped_or_failed_count += 1
                logger.info(f"AdminAction: Suscripción ID {subscription.pk} omitida por estar inactiva.")
                continue

            cycle_start_to_bill = get_due_cycle_start_date_for_subscription(subscription, today)

            if cycle_start_to_bill:
                invoice, created = generate_invoice_for_subscription(subscription, cycle_start_to_bill)
                if invoice:
                    if created:
                        newly_generated_count += 1
                    else:
                        already_existed_count += 1
                else:
                    skipped_or_failed_count += 1
            else:
                skipped_or_failed_count += 1

        if newly_generated_count > 0:
            self.message_user(request,
                              f"{newly_generated_count} nueva(s) factura(s) generada(s) exitosamente.",
                              messages.SUCCESS)
        if already_existed_count > 0:
             self.message_user(request,
                              f"{already_existed_count} factura(s) ya existían para el ciclo actual y fueron omitidas por la generación.",
                              messages.INFO)

        other_outcomes = skipped_or_failed_count
        if other_outcomes > 0 :
             self.message_user(request,
                              f"{other_outcomes} suscripciones fueron omitidas (no se cumplían criterios de facturación como ciclo/fechas o fallaron). Revise los logs para más detalles en caso de fallos.",
                              messages.WARNING)

        if newly_generated_count == 0 and already_existed_count == 0 and processed_subscriptions > 0 and skipped_or_failed_count == processed_subscriptions :
             self.message_user(request, "Ninguna de las suscripciones seleccionadas estaba lista para facturación hoy o cumplía los criterios.", messages.INFO)
        elif newly_generated_count == 0 and already_existed_count == 0 and processed_subscriptions == 0:
             self.message_user(request, "No se seleccionaron suscripciones.", messages.WARNING)

    generate_invoices_for_selected_action.short_description = "Generar Facturas para Seleccionadas (si aplica hoy)"


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'person', 'tenant', 'amount_due', 'due_date', 'status', 'paid_date', 'user_subscription')
    list_filter = ('tenant', 'status', 'due_date', 'paid_date', 'person__full_name')
    search_fields = ('invoice_number', 'person__full_name', 'person__identifier', 'user_subscription__service__name', 'tenant__name')
    list_editable = ('status', 'paid_date')
    autocomplete_fields = ['person', 'user_subscription', 'tenant']
    date_hierarchy = 'due_date'
    fieldsets = (
        (None, {'fields': ('tenant', 'invoice_number', 'person', 'user_subscription', 'status')}),
        ('Montos y Fechas', {'fields': ('amount_due', 'due_date', 'paid_date')}),
        ('Notas Adicionales', {'fields': ('notes',), 'classes': ('collapse',)}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(ControlDevice)
class ControlDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'device_id', 'tenant', 'access_point', 'mqtt_topic', 'is_active', 'ip_address')
    list_filter = ('tenant', 'is_active', 'access_point__name')
    search_fields = ('name', 'device_id', 'mqtt_topic', 'access_point__name', 'ip_address', 'tenant__name')
    list_editable = ('is_active', 'mqtt_topic')
    autocomplete_fields = ['access_point', 'tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'name', 'device_id', 'is_active')}),
        ('Asignación y Configuración MQTT', {'fields': ('access_point', 'mqtt_topic')}),
        ('Información Adicional (Opcional)', {'fields': ('ip_address', 'notes', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('person', 'invoice', 'tenant', 'amount', 'payment_date', 'payment_method', 'processed_for_access', 'created_at')
    list_filter = ('tenant', 'payment_method', 'processed_for_access', 'payment_date', 'person__full_name', 'invoice__invoice_number')
    search_fields = ('person__full_name', 'person__identifier', 'invoice__invoice_number', 'reference_number', 'amount', 'tenant__name')
    list_editable = ('processed_for_access',)
    date_hierarchy = 'payment_date'
    autocomplete_fields = ['person', 'invoice', 'tenant']
    fieldsets = (
        (None, {'fields': ('tenant', 'person', 'invoice', 'amount', 'payment_date', 'payment_method')}),
        ('Detalles Adicionales', {'fields': ('reference_number', 'notes')}),
        ('Estado de Procesamiento', {'fields': ('processed_for_access',)}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')
    actions = ['process_selected_payments_action']

    def process_selected_payments_action(self, request, queryset):
        processed_count = 0; already_processed_count = 0; failed_count = 0
        for payment in queryset:
            if payment.processed_for_access: already_processed_count +=1; continue
            success = process_payment_for_access(payment)
            if success: processed_count += 1
            else: failed_count +=1
        if processed_count > 0: self.message_user(request, f"{processed_count} pago(s) procesado(s) exitosamente.", messages.SUCCESS)
        if already_processed_count > 0: self.message_user(request, f"{already_processed_count} pago(s) ya habían sido procesados.", messages.INFO)
        if failed_count > 0: self.message_user(request, f"{failed_count} pago(s) no pudieron ser procesados (p.ej., persona no asignada al pago, o error al intentar actualizar/crear permisos). Revise los logs para detalles.", messages.ERROR)
    process_selected_payments_action.short_description = "Procesar Pagos para Activar/Extender Acceso"

# Ensure Token is not registered again if it was by default by DRF's admin
if admin.site.is_registered(Token):
    admin.site.unregister(Token)

# Re-register Token if needed, or if it's not registered by DRF by default with some ModelAdmins.
# For now, let's assume it's handled or not critical for this step.
# admin.site.register(Token) # This might cause issues if DRF already registered it.
# It's better to use @admin.register(Token) class TokenAdmin(admin.ModelAdmin): pass if customization is needed.
# For now, the previous simple registration is fine if it works, or it can be removed if DRF handles it.
# The prompt doesn't ask to modify Token admin, so keeping its existing simple registration logic.
# The simple registration for Token was:
# if not admin.site.is_registered(Token):
# admin.site.register(Token)
# This will be kept by the overwrite if it was part of the original file structure.
# Based on the read_files output, it was simply registered.
# The overwrite will replace the whole file, so I need to ensure it's correctly handled.
# The original simple registrations are removed by @admin.register for the models we are customizing.
# So, I only need to ensure Token is registered if it's not already covered.
# The read_file output shows Token was registered with a simple if check.
# This will be preserved if not explicitly overwritten by a new @admin.register(Token).

# Re-adding simple registration for Token if it's not covered by a custom admin class above
# and was present in the original file.
if not admin.site.is_registered(Token):
    admin.site.register(Token)
