from .models import AccessLog, Person, AccessPoint, AccessPermission, ControlDevice, Payment, Invoice # Invoice model import added
from django.utils import timezone
import paho.mqtt.publish as publish
from django.conf import settings
import logging
from datetime import timedelta # timedelta añadido

logger = logging.getLogger(__name__)

def record_access_attempt(qr_data_received, access_was_granted, event_type_observed="acceso_general", user_id_info=None):
    try:
        log_entry = AccessLog.objects.create(
            qr_data=qr_data_received, access_granted=access_was_granted,
            event_type=event_type_observed, user_id=user_id_info
        )
        return log_entry
    except Exception as e:
        logger.error(f"Error al crear la entrada de log en BD para QR '{qr_data_received}': {e}")
        return None

def verify_access_with_models(qr_identifier, access_point_name):
    person = None; access_point_obj = None; access_granted = False; user_id_for_log = None
    try:
        person = Person.objects.get(identifier=qr_identifier)
        user_id_for_log = person.identifier
        try:
            access_point_obj = AccessPoint.objects.get(name=access_point_name)
            permission = AccessPermission.objects.get(person=person, access_point=access_point_obj)
            now = timezone.now(); is_valid_time = True
            if permission.valid_from and permission.valid_from > now: is_valid_time = False
            if permission.valid_until and permission.valid_until < now: is_valid_time = False
            if permission.is_active and is_valid_time: access_granted = True
        except AccessPoint.DoesNotExist: logger.warning(f"Punto de acceso '{access_point_name}' no encontrado...")
        except AccessPermission.DoesNotExist: logger.info(f"Permiso no encontrado para QR '{qr_identifier}' en AP '{access_point_name}'.")
    except Person.DoesNotExist:
        logger.info(f"Persona con identificador QR '{qr_identifier}' no encontrada.")
        user_id_for_log = qr_identifier
    except Exception as e:
        logger.error(f"Error inesperado en verify_access_with_models para QR '{qr_identifier}': {e}")
        user_id_for_log = qr_identifier; access_granted = False
    if access_granted and access_point_obj:
        active_control_devices = ControlDevice.objects.filter(access_point=access_point_obj, is_active=True)
        if not active_control_devices.exists(): logger.warning(f"Acceso concedido en {access_point_obj.name}, pero no hay ControlDevices activos...")
        else:
            for device in active_control_devices:
                logger.info(f"Intentando abrir {access_point_obj.name} via {device.name} en {device.mqtt_topic}")
                success = publish_mqtt_message(topic=device.mqtt_topic, payload="OPEN")
                if success: logger.info(f"MQTT: Mensaje 'OPEN' publicado a {device.mqtt_topic} para {device.name}.")
                else: logger.error(f"MQTT: Fallo al publicar 'OPEN' a {device.mqtt_topic} para {device.name}.")
    record_access_attempt(qr_data_received=qr_identifier, access_was_granted=access_granted, event_type_observed="verificacion_modelo_django", user_id_info=user_id_for_log)
    return access_granted

def publish_mqtt_message(topic, payload, retain=False):
    try:
        auth_dict = None
        mqtt_user = getattr(settings, 'MQTT_USERNAME', None); mqtt_pass = getattr(settings, 'MQTT_PASSWORD', None)
        if mqtt_user and mqtt_pass: auth_dict = {'username': mqtt_user, 'password': mqtt_pass}
        publish.single(topic, payload=payload, qos=1, retain=retain, hostname=settings.MQTT_BROKER_HOST, port=settings.MQTT_BROKER_PORT, client_id=settings.MQTT_CLIENT_ID, auth=auth_dict)
        logger.info(f"MQTT: Publicado en tópico '{topic}': {payload}")
        return True
    except ConnectionRefusedError:
        logger.error(f"MQTT Error: Conexión rechazada al broker {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}. Verifica que el broker esté activo y accesible.") # Corrected full message
        return False
    except Exception as e:
        logger.error(f"MQTT Error: No se pudo publicar en tópico '{topic}'. Error: {e}")
        return False

def process_payment_for_access(payment: Payment):
    if not payment.person:
        logger.warning(f"Pago ID {payment.pk} no tiene una persona asociada. No se puede procesar para acceso.")
        return False
    if payment.processed_for_access: # Check if already processed for access logic
        logger.info(f"Pago ID {payment.pk} para {payment.person.full_name} ya ha sido procesado para acceso.")
        # Even if processed for access, it might not have been applied to an invoice if invoice logic was added later.
        # However, the main goal of this function is access processing, so if that's done, we might return True.
        # For this refactoring, we'll assume if processed_for_access is True, its invoice status is also final.
        return True

    # --- Logic for AccessPermission (existing) ---
    person_permissions = AccessPermission.objects.filter(person=payment.person)
    access_duration_days = 30

    if not person_permissions.exists():
        default_ap_name = "Entrada Principal"
        access_point_to_grant = AccessPoint.objects.first()
        if not access_point_to_grant:
            try: access_point_to_grant = AccessPoint.objects.get(name=default_ap_name)
            except AccessPoint.DoesNotExist:
                logger.error(f"No se encontró AccessPoint por defecto para {payment.person.full_name}.")
                return False
        try:
            new_permission = AccessPermission.objects.create(
                person=payment.person, access_point=access_point_to_grant, is_active=True,
                valid_from=payment.payment_date,
                valid_until=payment.payment_date + timedelta(days=access_duration_days)
            )
            logger.info(f"Creado nuevo permiso para {payment.person.full_name} en {access_point_to_grant.name} válido hasta {new_permission.valid_until.strftime('%Y-%m-%d %H:%M')}.")
        except Exception as e:
             logger.error(f"Error creando nuevo permiso para {payment.person.full_name} en {access_point_to_grant.name}: {e}")
             return False
    else:
        for permission in person_permissions:
            permission.is_active = True
            current_valid_until = permission.valid_until

            if not current_valid_until or current_valid_until < payment.payment_date:
                permission.valid_from = payment.payment_date
                permission.valid_until = payment.payment_date + timedelta(days=access_duration_days)
            else:
                permission.valid_until = current_valid_until + timedelta(days=access_duration_days)
                if not permission.valid_from or permission.valid_from > payment.payment_date:
                     permission.valid_from = payment.payment_date
            permission.save()
            logger.info(f"Permiso actualizado para {payment.person.full_name} en {permission.access_point.name}, válido hasta {permission.valid_until.strftime('%Y-%m-%d %H:%M')}.")
    # --- End of AccessPermission Logic ---

    # --- New Logic to Apply Payment to Invoice ---
    invoice_processed_this_run = False
    if not payment.invoice: # Only attempt if payment is not already linked to an invoice
        # Find the oldest pending/overdue invoice for this person that this payment can cover
        outstanding_invoices = Invoice.objects.filter(
            person=payment.person,
            status__in=['pending', 'overdue']
        ).order_by('due_date', 'created_at')

        for invoice_to_pay in outstanding_invoices:
            if payment.amount >= invoice_to_pay.amount_due:
                invoice_to_pay.status = 'paid'
                # Use payment_date (which is a DateTimeField) as paid_date (DateField)
                # Ensure payment_date is converted to date if necessary, though Django might handle it.
                invoice_to_pay.paid_date = payment.payment_date.date()
                invoice_to_pay.save(update_fields=['status', 'paid_date', 'updated_at'])

                payment.invoice = invoice_to_pay # Link payment to this invoice

                logger.info(f"Pago ID {payment.pk} (${payment.amount}) aplicado a Factura {invoice_to_pay.invoice_number} (${invoice_to_pay.amount_due}). Factura marcada como pagada.")
                invoice_processed_this_run = True
                break # Apply one payment to one invoice for now
            # else:
                # logger.info(f"Pago ID {payment.pk} (${payment.amount}) es menor que la factura pendiente {invoice_to_pay.invoice_number} (${invoice_to_pay.amount_due}). No se aplica a esta factura.")

    # Mark payment as processed for access logic (original intent)
    payment.processed_for_access = True

    # Fields to update in the final save
    update_fields_for_payment = ['processed_for_access', 'updated_at']
    if invoice_processed_this_run: # If we linked an invoice in this run
        update_fields_for_payment.append('invoice')

    payment.save(update_fields=update_fields_for_payment)

    if invoice_processed_this_run:
        logger.info(f"Pago ID {payment.pk} para {payment.person.full_name} marcado como procesado y vinculado a factura {payment.invoice.invoice_number}.")
    elif payment.invoice and not invoice_processed_this_run: # Had an invoice from before, not changed in this run
        logger.info(f"Pago ID {payment.pk} para {payment.person.full_name} marcado como procesado, ya estaba asignado a Factura {payment.invoice.invoice_number}.")
    else: # No invoice linked in this run, and no pre-existing link
        logger.info(f"Pago ID {payment.pk} para {payment.person.full_name} marcado como procesado para acceso, pero no se aplicó/vinculó a ninguna factura pendiente específica en esta ejecución.")

    return True
