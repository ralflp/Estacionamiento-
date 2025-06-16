from django.urls import path
# Asegúrate de que views sea importado correctamente. Si solo tienes 'from . import views',
# y las vistas están en ese archivo, está bien.
from . import views

app_name = 'log_viewer_app'

urlpatterns = [
    # URLs existentes
    path('logs/', views.access_log_list_view, name='access_log_list'),
    path('persons/', views.person_list_view, name='person_list'),
    path('persons/add/', views.person_create_view, name='person_create'),
    path('vehicles/', views.vehicle_list_view, name='vehicle_list'),
    path('vehicles/add/', views.vehicle_create_view, name='vehicle_create'),
    path('permissions/', views.permission_list_view, name='permission_list'),
    path('permissions/assign/', views.permission_create_view, name='permission_create'),

    # Nuevas URLs para Dispositivos de Control
    path('control-devices/', views.control_device_list_view, name='control_device_list'),
    path('control-devices/add/', views.control_device_create_view, name='control_device_create'),
    path('control-devices/<int:pk>/update/', views.control_device_update_view, name='control_device_update'),
]
