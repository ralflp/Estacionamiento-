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

    # Nuevas URLs para Vehículos
    path('vehicles/', views.vehicle_list_view, name='vehicle_list'),
    path('vehicles/add/', views.vehicle_create_view, name='vehicle_create'),
    # Más adelante se podrían añadir URLs para editar, eliminar, etc.
]
