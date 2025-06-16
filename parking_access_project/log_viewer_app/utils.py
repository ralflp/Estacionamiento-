from .models import AccessLog, Person, AccessPoint, AccessPermission
from django.utils import timezone

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

def verify_access_with_models(qr_identifier, access_point_name):
    """
    Verifica el acceso basado en el identificador QR y el nombre del punto de acceso,
    utilizando los modelos Person, AccessPoint y AccessPermission.
    También registra el intento de acceso.
    """
    person = None
    access_point = None
    access_granted = False
    user_id_for_log = None # Puede ser el person.identifier o el qr_identifier

    try:
        # Intenta encontrar a la persona por su identificador (que se asume es el contenido del QR)
        person = Person.objects.get(identifier=qr_identifier)
        user_id_for_log = person.identifier # Usar el identificador de persona para el log

        try:
            access_point = AccessPoint.objects.get(name=access_point_name)

            # Buscar un permiso específico para esta persona y punto de acceso
            permission = AccessPermission.objects.get(
                person=person,
                access_point=access_point
            )

            # Verificar si el permiso está activo y dentro del rango de validez temporal
            now = timezone.now()
            is_valid_time = True # Asumir válido a menos que se demuestre lo contrario

            # Chequear validez temporal si las fechas están establecidas
            if permission.valid_from and permission.valid_from > now:
                is_valid_time = False
            if permission.valid_until and permission.valid_until < now:
                is_valid_time = False

            if permission.is_active and is_valid_time:
                access_granted = True

        except AccessPoint.DoesNotExist:
            # Punto de acceso no encontrado. Acceso denegado.
            # El log se registrará con access_granted = False (ya es su valor por defecto)
            pass
        except AccessPermission.DoesNotExist:
            # Permiso no encontrado para esta persona y punto de acceso. Acceso denegado.
            pass

    except Person.DoesNotExist:
        # Persona no encontrada con ese qr_identifier. Acceso denegado.
        user_id_for_log = qr_identifier # Usar el qr_identifier original si la persona no se encontró
        pass
    except Exception as e:
        # Cualquier otra excepción inesperada, registrar y denegar acceso por seguridad.
        # Considerar loguear este error 'e' a un sistema de monitoreo en producción.
        # print(f"Error inesperado en verify_access_with_models: {e}") # Para depuración
        user_id_for_log = qr_identifier # Usar el qr_identifier original
        access_granted = False # Asegurar que el acceso sea denegado


    # Registrar el intento de acceso usando la función existente
    record_access_attempt(
        qr_data_received=qr_identifier,
        access_was_granted=access_granted,
        event_type_observed="verificacion_modelo_django", # Tipo de evento más específico
        user_id_info=user_id_for_log
    )

    return access_granted

# Ejemplo de cómo se podría probar manualmente (no se ejecutará automáticamente por el subtask):
# if __name__ == '__main__':
#     # Configurar entorno Django para ejecución standalone
#     import os
#     import django
#     # Asegúrate de que DJANGO_SETTINGS_MODULE apunte al settings.py de tu proyecto Django
#     os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'parking_access_project.settings')
#     django.setup()

#     # --- Crear datos de prueba ---
#     # (Esto es solo un ejemplo. En un caso real, estos datos se gestionarían
#     # a través del panel de administración de Django, fixtures, o scripts de populación.)

#     # Crear una Persona
#     persona_test, created_p = Person.objects.get_or_create(
#         full_name="Ana Torres",
#         identifier="QR_ANA_001"
#     )
#     if created_p: print(f"Persona creada: {persona_test}")

#     # Crear un Punto de Acceso
#     punto_acceso_test, created_ap = AccessPoint.objects.get_or_create(
#         name="Entrada Principal Edificio A"
#     )
#     if created_ap: print(f"Punto de acceso creado: {punto_acceso_test}")

#     # Conceder Permiso a Ana para la Entrada Principal
#     permiso_test, created_perm = AccessPermission.objects.get_or_create(
#         person=persona_test,
#         access_point=punto_acceso_test,
#         defaults={
#             'is_active': True,
#             # 'valid_from' usará timezone.now por defecto si no se especifica
#             # 'valid_until': None (sin caducidad)
#         }
#     )
#     if created_perm: print(f"Permiso creado: {permiso_test}")


#     # --- Probar la función verify_access_with_models ---
#     print("\nIntentando verificar acceso para QR_ANA_001 en 'Entrada Principal Edificio A':")
#     if verify_access_with_models("QR_ANA_001", "Entrada Principal Edificio A"):
#         print("Resultado: Acceso Permitido")
#     else:
#         print("Resultado: Acceso Denegado")

#     print("\nIntentando verificar acceso para QR_DESCONOCIDO en 'Entrada Principal Edificio A':")
#     if verify_access_with_models("QR_DESCONOCIDO_999", "Entrada Principal Edificio A"):
#         print("Resultado: Acceso Permitido")
#     else:
#         print("Resultado: Acceso Denegado")

#     print("\nIntentando verificar acceso para QR_ANA_001 en 'Puerta Trasera' (Punto de acceso no existente o sin permiso):")
#     if verify_access_with_models("QR_ANA_001", "Puerta Trasera"):
#         print("Resultado: Acceso Permitido")
#     else:
#         print("Resultado: Acceso Denegado")

#     # Mostrar todos los logs creados durante esta prueba (opcional)
#     # print("\nRegistros de acceso creados durante la prueba:")
#     # for log_item in AccessLog.objects.filter(event_type_observed="verificacion_modelo_django"):
#     # print(log_item)
