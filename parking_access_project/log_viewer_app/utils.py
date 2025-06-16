from .models import AccessLog # Importar el modelo AccessLog

def record_access_attempt(qr_data_received, access_was_granted, event_type_observed="acceso_general", user_id_info=None):
    """
    Crea y guarda una entrada de registro de acceso en la base de datos.
    """
    try:
        log_entry = AccessLog.objects.create(
            qr_data=qr_data_received,
            access_granted=access_was_granted,
            event_type=event_type_observed,
            user_id=user_id_info
        )
        # print(f"Log entry created: {log_entry}") # Opcional, para depuración
        return log_entry
    except Exception as e:
        # print(f"Error creating log entry: {e}") # Opcional, para depuración
        return None

# Ejemplo de cómo se podría probar manualmente (no se ejecutará automáticamente por el subtask):
# if __name__ == '__main__':
#   # Para ejecutar esto directamente, necesitarías configurar el entorno de Django
#   # import os
#   # import django
#   # os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'parking_access_project.settings')
#   # django.setup()
#
#   # record_access_attempt("QR_TEST_DJANGO_1", True)
#   # record_access_attempt("QR_TEST_DJANGO_2", False, user_id_info="user007")
#   # print("Ejemplos de registros creados (si se ejecuta en entorno Django).")
