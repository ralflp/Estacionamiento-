from django.contrib import admin
from .models import AccessLog, Person, Vehicle, AccessPoint, AccessPermission, ControlDevice # ControlDevice es nuevo aquí

# Register your models here.

# Simple registrations (manteniendo los existentes)
admin.site.register(AccessLog)
admin.site.register(Person)
admin.site.register(Vehicle)
admin.site.register(AccessPoint)

# Para AccessPermission, si se quiere usar una clase Admin personalizada en el futuro:
# Por ahora, usamos el registro simple que ya estaba (o se puede cambiar a uno personalizado).
# Si no está registrado, lo registramos simple.
if not admin.site.is_registered(AccessPermission):
    admin.site.register(AccessPermission)


# Clase ModelAdmin personalizada para ControlDevice
@admin.register(ControlDevice)
class ControlDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'device_id', 'access_point', 'mqtt_topic', 'is_active', 'ip_address')
    list_filter = ('is_active', 'access_point__name') # Filtrar por estado y nombre del punto de acceso
    search_fields = ('name', 'device_id', 'mqtt_topic', 'access_point__name', 'ip_address') # Campos de búsqueda
    list_editable = ('is_active', 'mqtt_topic') # Permitir editar estos campos directamente en la lista

    fieldsets = (
        (None, {
            'fields': ('name', 'device_id', 'is_active')
        }),
        ('Asignación y Configuración MQTT', {
            'fields': ('access_point', 'mqtt_topic')
        }),
        ('Información Adicional (Opcional)', {
            'fields': ('ip_address', 'notes', 'created_at', 'updated_at'), # Añadido created_at y updated_at
            'classes': ('collapse',), # Hacer esta sección colapsable
        }),
    )
    readonly_fields = ('created_at', 'updated_at') # Mostrar created_at y updated_at como solo lectura

# Ejemplo de una clase ModelAdmin más personalizada para AccessPermission (opcional)
# (Se mantiene el código de ejemplo comentado del prompt anterior, pero no se activa)
# class AccessPermissionAdmin(admin.ModelAdmin):
#     list_display = ('person', 'access_point', 'is_active', 'valid_from', 'valid_until', 'created_at')
#     list_filter = ('is_active', 'access_point', 'person')
#     search_fields = ('person__full_name', 'person__identifier', 'access_point__name')
#     date_hierarchy = 'created_at'

# if admin.site.is_registered(AccessPermission):
#     admin.site.unregister(AccessPermission)
# admin.site.register(AccessPermission, AccessPermissionAdmin)
