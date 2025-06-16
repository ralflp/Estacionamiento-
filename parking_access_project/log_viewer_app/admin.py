from django.contrib import admin
from .models import AccessLog, Person, Vehicle, AccessPoint, AccessPermission

# Register your models here.

# A simple registration for all models:
admin.site.register(AccessLog)
admin.site.register(Person)
admin.site.register(Vehicle)
admin.site.register(AccessPoint)
admin.site.register(AccessPermission)

# Example of a more customized admin interface for AccessPermission (optional)
# class AccessPermissionAdmin(admin.ModelAdmin):
#     list_display = ('person', 'access_point', 'is_active', 'valid_from', 'valid_until', 'created_at')
#     list_filter = ('is_active', 'access_point', 'person') # Use direct FK fields for filtering
#     search_fields = ('person__full_name', 'person__identifier', 'access_point__name')
#     date_hierarchy = 'created_at' # Allows quick date navigation

# To use the custom admin, you would unregister the simple one first if already registered,
# or just register with the custom class directly:
# if admin.site.is_registered(AccessPermission):
# admin.site.unregister(AccessPermission)
# admin.site.register(AccessPermission, AccessPermissionAdmin)
