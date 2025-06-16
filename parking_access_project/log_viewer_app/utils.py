from .models import AccessLog, Person, AccessPoint, AccessPermission, ControlDevice # ControlDevice añadido
from django.utils import timezone
import paho.mqtt.publish as publish
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

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
        return log_entry
    except Exception as e:
        logger.error(f"Error al crear la entrada de log en BD para QR '{qr_data_received}': {e}")
        return None

def verify_access_with_models(qr_identifier, access_point_name):
    """
    Verifica el acceso basado en el identificador QR y el nombre del punto de acceso,
    utilizando los modelos Person, AccessPoint y AccessPermission.
    Publica un mensaje MQTT si el acceso es concedido y hay dispositivos de control.
    También registra el intento de acceso.
    """
    person = None
    access_point_obj = None # Renombrado para claridad
    access_granted = False
    user_id_for_log = None

    try:
        person = Person.objects.get(identifier=qr_identifier)
        user_id_for_log = person.identifier

        try:
            access_point_obj = AccessPoint.objects.get(name=access_point_name)
            permission = AccessPermission.objects.get(
                person=person,
                access_point=access_point_obj
            )

            now = timezone.now()
            is_valid_time = True
            if permission.valid_from and permission.valid_from > now:
                is_valid_time = False
            if permission.valid_until and permission.valid_until < now:
                is_valid_time = False

            if permission.is_active and is_valid_time:
                access_granted = True

        except AccessPoint.DoesNotExist:
            logger.warning(f"Punto de acceso '{access_point_name}' no encontrado al verificar acceso para QR '{qr_identifier}'.")
        except AccessPermission.DoesNotExist:
            logger.info(f"Permiso no encontrado para QR '{qr_identifier}' en AP '{access_point_name}'.")

    except Person.DoesNotExist:
        logger.info(f"Persona con identificador QR '{qr_identifier}' no encontrada.")
        user_id_for_log = qr_identifier
    except Exception as e:
        logger.error(f"Error inesperado en verify_access_with_models para QR '{qr_identifier}': {e}")
        user_id_for_log = qr_identifier
        access_granted = False # Asegurar denegación en caso de error inesperado

    # Lógica de publicación MQTT si el acceso es concedido
    if access_granted and access_point_obj: # access_point_obj debe existir si se concedió acceso basado en permiso
        active_control_devices = ControlDevice.objects.filter(access_point=access_point_obj, is_active=True)
        if not active_control_devices.exists():
            logger.warning(f"Acceso concedido en {access_point_obj.name}, pero no hay ControlDevices activos configurados para este punto de acceso.")
        else:
            for device in active_control_devices:
                logger.info(f"Intentando abrir {access_point_obj.name} via dispositivo {device.name} en tópico {device.mqtt_topic}")
                open_payload = "OPEN" # Payload podría ser configurable por dispositivo en el futuro
                success = publish_mqtt_message(topic=device.mqtt_topic, payload=open_payload)
                if success:
                    logger.info(f"MQTT: Mensaje '{open_payload}' publicado exitosamente a {device.mqtt_topic} para {device.name}.")
                else:
                    # El error ya se loguea dentro de publish_mqtt_message
                    logger.error(f"MQTT: Fallo al publicar mensaje '{open_payload}' a {device.mqtt_topic} para {device.name} (revisar logs anteriores para detalles).")

    # Registrar el intento de acceso (siempre se hace)
    record_access_attempt(
        qr_data_received=qr_identifier,
        access_was_granted=access_granted,
        event_type_observed="verificacion_modelo_django",
        user_id_info=user_id_for_log
    )

    return access_granted

def publish_mqtt_message(topic, payload, retain=False):
    """
    Publica un mensaje a un tópico MQTT especificado.
    """
    try:
        auth_dict = None
        mqtt_user = getattr(settings, 'MQTT_USERNAME', None)
        mqtt_pass = getattr(settings, 'MQTT_PASSWORD', None)

        if mqtt_user and mqtt_pass:
            auth_dict = {'username': mqtt_user, 'password': mqtt_pass}

        publish.single(
            topic,
            payload=payload,
            qos=1,
            retain=retain,
            hostname=settings.MQTT_BROKER_HOST,
            port=settings.MQTT_BROKER_PORT,
            client_id=settings.MQTT_CLIENT_ID,
            auth=auth_dict
        )
        logger.info(f"MQTT: Publicado en tópico '{topic}': {payload}")
        return True
    except ConnectionRefusedError:
        logger.error(f"MQTT Error: Conexión rechazada al broker {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}. Verifica que el broker esté activo y accesible.")
        return False
    except Exception as e:
        logger.error(f"MQTT Error: No se pudo publicar en tópico '{topic}'. Error: {e}")
        return False

# ... (Bloque if __name__ == '__main__' comentado) ...
