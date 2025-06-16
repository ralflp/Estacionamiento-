from django.urls import path
from . import views # Importa las vistas de la app

app_name = 'log_viewer_app' # Opcional, pero buena práctica para namespacing

urlpatterns = [
    path('logs/', views.access_log_list_view, name='access_log_list'),
    # Podrías definir una ruta raíz para la app también si quieres, ej:
    # path('', views.access_log_list_view, name='app_home'),
]
