from django.contrib import admin, messages
from .models import (
    AccessLog, Person, Vehicle, AccessPoint,
    AccessPermission, ControlDevice, Payment,
    Service, UserSubscription, Invoice
)
from .utils import process_payment_for_access
from .billing_utils import get_due_cycle_start_date_for_subscription, generate_invoice_for_subscription
from django.utils import timezone
from rest_framework.authtoken.models import Token
import logging # Added

logger = logging.getLogger(__name__) # Added

# Register your models here.

# Simple registration for models not requiring special admin features yet
if not admin.site.is_registered(AccessLog):
    admin.site.register(AccessLog)
if not admin.site.is_registered(Vehicle): # Vehicle does not seem to be a target of autocomplete_fields yet
    admin.site.register(Vehicle)
if not admin.site.is_registered(AccessPermission): # AccessPermission is not a target of autocomplete_fields
    admin.site.register(AccessPermission)
if not admin.site.is_registered(Token):
    admin.site.register(Token)

# Custom ModelAdmins for models that are targets of autocomplete_fields or need customization

@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'identifier', 'user', 'created_at', 'updated_at')
    search_fields = ('full_name', 'identifier', 'user__username') # Added user__username
    list_filter = ('created_at', 'updated_at')
    autocomplete_fields = ['user'] # If you want to search for users when linking

@admin.register(AccessPoint)
class AccessPointAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')
    search_fields = ('name', 'description')
    list_filter = ('created_at',)

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'created_at', 'updated_at')
    search_fields = ('name', 'description') # search_fields was already defined
    list_filter = ('price',)

@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('person', 'service', 'start_date', 'end_date', 'billing_cycle', 'get_effective_price', 'is_active')
    list_filter = ('is_active', 'billing_cycle', 'service__name', 'person__full_name')
    search_fields = ('person__full_name', 'person__identifier', 'service__name') # search_fields was already defined
    list_editable = ('is_active', 'end_date')
    autocomplete_fields = ['person', 'service']
    date_hierarchy = 'start_date'
    fieldsets = (
        (None, {'fields': ('person', 'service', 'is_active')}),
        ('Detalles de Suscripción', {'fields': ('start_date', 'end_date', 'billing_cycle', 'billing_cycle_anchor_day', 'price_override')}), # Added billing_cycle_anchor_day
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
                # This check is slightly redundant as get_due_cycle_start_date_for_subscription also checks it,
                # but it's a quick explicit skip.
                skipped_or_failed_count += 1
                logger.info(f"AdminAction: Suscripción ID {subscription.pk} omitida por estar inactiva.")
                continue

            # Note: The admin action, unlike the batch command, might ignore billing_cycle_anchor_day
            # to allow manual generation if a cycle is due.
            # For consistency with prompt, get_due_cycle_start_date_for_subscription is called,
            # which itself does NOT check anchor day. The batch command DOES check anchor day before calling the helper.
            # If we wanted this action to *only* bill if it's the anchor day:
            # if today.day != subscription.billing_cycle_anchor_day:
            #    skipped_or_failed_count += 1
            #    logger.info(f"AdminAction: Sub ID {subscription.pk} skip: today not anchor day.")
            #    continue

            cycle_start_to_bill = get_due_cycle_start_date_for_subscription(subscription, today)

            if cycle_start_to_bill:
                invoice, created = generate_invoice_for_subscription(subscription, cycle_start_to_bill)
                if invoice:
                    if created:
                        newly_generated_count += 1
                    else:
                        already_existed_count += 1
                else: # Falla dentro de generate_invoice_for_subscription
                    skipped_or_failed_count += 1
            else: # No es momento de facturar esta suscripción según las reglas de get_due_cycle_start_date_for_subscription
                skipped_or_failed_count += 1

        if newly_generated_count > 0:
            self.message_user(request,
                              f"{newly_generated_count} nueva(s) factura(s) generada(s) exitosamente.",
                              messages.SUCCESS)
        if already_existed_count > 0:
             self.message_user(request,
                              f"{already_existed_count} factura(s) ya existían para el ciclo actual y fueron omitidas por la generación.",
                              messages.INFO)

        # Consolidate skipped/failed messages
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
    list_display = ('invoice_number', 'person', 'amount_due', 'due_date', 'status', 'paid_date', 'user_subscription')
    list_filter = ('status', 'due_date', 'paid_date', 'person__full_name')
    search_fields = ('invoice_number', 'person__full_name', 'person__identifier', 'user_subscription__service__name') # search_fields was already defined
    list_editable = ('status', 'paid_date')
    autocomplete_fields = ['person', 'user_subscription']
    date_hierarchy = 'due_date'
    fieldsets = (
        (None, {'fields': ('invoice_number', 'person', 'user_subscription', 'status')}),
        ('Montos y Fechas', {'fields': ('amount_due', 'due_date', 'paid_date')}),
        ('Notas Adicionales', {'fields': ('notes',), 'classes': ('collapse',)}),
        ('Auditoría', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)})
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(ControlDevice)
class ControlDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'device_id', 'access_point', 'mqtt_topic', 'is_active', 'ip_address')
    list_filter = ('is_active', 'access_point__name')
    search_fields = ('name', 'device_id', 'mqtt_topic', 'access_point__name', 'ip_address')
    list_editable = ('is_active', 'mqtt_topic')
    autocomplete_fields = ['access_point']
    fieldsets = (
        (None, {'fields': ('name', 'device_id', 'is_active')}),
        ('Asignación y Configuración MQTT', {'fields': ('access_point', 'mqtt_topic')}),
        ('Información Adicional (Opcional)', {'fields': ('ip_address', 'notes', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('person', 'invoice', 'amount', 'payment_date', 'payment_method', 'reference_number', 'processed_for_access', 'created_at')
    list_filter = ('payment_method', 'processed_for_access', 'payment_date', 'person__full_name', 'invoice__invoice_number')
    search_fields = ('person__full_name', 'person__identifier', 'invoice__invoice_number', 'reference_number', 'amount')
    list_editable = ('processed_for_access',)
    date_hierarchy = 'payment_date'
    autocomplete_fields = ['person', 'invoice']
    fieldsets = (
        (None, {'fields': ('person', 'invoice', 'amount', 'payment_date', 'payment_method')}),
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
