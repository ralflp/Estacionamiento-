from django.shortcuts import render
from .models import AccessLog # Asegúrate de que AccessLog esté importado

def access_log_list_view(request):
    # Recuperar todos los registros de acceso, ordenados por fecha descendente
    logs = AccessLog.objects.all().order_by('-timestamp')

    context = {
        'access_logs': logs,
        'page_title': 'Registros de Acceso' # Un título de ejemplo para la página
    }

    # El nombre de la plantilla 'log_viewer_app/access_log_list.html' se creará en el siguiente paso
    return render(request, 'log_viewer_app/access_log_list.html', context)

# La función record_access_attempt NO debe estar en views.py, debe estar en utils.py
# Si por error se añadió aquí en un paso anterior, debería eliminarse de views.py
# y asegurarse de que está en log_viewer_app/utils.py
