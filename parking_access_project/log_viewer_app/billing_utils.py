from django.utils import timezone
from datetime import timedelta
# Suponiendo que Invoice y UserSubscription están en models.py de la misma app
# (log_viewer_app en este caso)
from .models import Invoice, UserSubscription, Person, Service # Person y Service para type hints
from django.conf import settings # Import settings
from django.utils import timezone # Ensure timezone is imported
from datetime import timedelta, date # Ensure date is imported
from dateutil.relativedelta import relativedelta # For cycle calculations
import logging

logger = logging.getLogger(__name__)

def generate_invoice_for_subscription(subscription: UserSubscription, cycle_start_date: date) -> tuple[Invoice | None, bool]:
    """
    Genera una nueva factura para una suscripción y un ciclo de facturación específico.

    Args:
        subscription: La instancia de UserSubscription para la cual generar la factura.
        cycle_start_date: La fecha de inicio del ciclo de facturación actual para esta factura.
            Debe ser un objeto date de Python.

    Returns:
        La instancia de Invoice creada, o None si ocurre un error o se omite la creación.
    """
    if not isinstance(subscription, UserSubscription):
        logger.error(f"Argumento 'subscription' inválido: se esperaba UserSubscription, se obtuvo {type(subscription)}.")
        return None, False
    # cycle_start_date ya está type-hinted, pero una validación en tiempo de ejecución podría ser útil
    # if not isinstance(cycle_start_date, timezone.datetime.date): # o datetime.date
    #     logger.error(f"Argumento 'cycle_start_date' inválido: se esperaba date, se obtuvo {type(cycle_start_date)}.")
    #     return None, False


    if not subscription.is_active:
        logger.warning(f"Intento de generar factura para suscripción inactiva ID {subscription.pk} de {subscription.person}. Omitiendo.")
        return None, False

    # Validar que el cycle_start_date esté dentro del rango de la suscripción
    if cycle_start_date < subscription.start_date:
        logger.warning(f"Intento de generar factura para suscripción ID {subscription.pk} con fecha de ciclo ({cycle_start_date}) anterior a la fecha de inicio de la suscripción ({subscription.start_date}). Omitiendo.")
        return None, False

    if subscription.end_date and cycle_start_date > subscription.end_date:
        logger.warning(f"Intento de generar factura para suscripción ID {subscription.pk} con fecha de ciclo ({cycle_start_date}) posterior a la fecha de fin de la suscripción ({subscription.end_date}). Omitiendo.")
        return None, False

    # Generar un número de factura único y predecible para este ciclo
    # Esto ayuda a prevenir duplicados si la tarea se ejecuta múltiples veces por error.
    proposed_invoice_number = f"SUB-{subscription.pk}-{cycle_start_date.strftime('%Y%m%d')}"

    existing_invoice = Invoice.objects.filter(invoice_number=proposed_invoice_number).first()
    if existing_invoice:
        logger.info(f"Factura {proposed_invoice_number} ya existe para la suscripción ID {subscription.pk} (ciclo {cycle_start_date}). Devolviendo existente.")
        return existing_invoice, False # Devolver la factura existente, created = False

    try:
        amount = subscription.get_effective_price()

        # Calcular due_date usando settings.INVOICE_DUE_DAYS
        due_date_offset_days = settings.INVOICE_DUE_DAYS
        due_date = cycle_start_date + timedelta(days=due_date_offset_days)

        invoice = Invoice.objects.create(
            person=subscription.person,
            user_subscription=subscription,
            invoice_number=proposed_invoice_number,
            cycle_start_date=cycle_start_date, # Guardar el cycle_start_date
            amount_due=amount,
            due_date=due_date,
            status='pending', # Estado inicial para una nueva factura generada
            notes=f"Factura generada para el servicio '{subscription.service.name}' para el ciclo iniciado el {cycle_start_date.strftime('%Y-%m-%d')}."
            # paid_date se establecerá cuando se registre un pago para esta factura
        )
        logger.info(f"Factura {invoice.invoice_number} creada para {subscription.person.full_name} por ${amount:.2f}, vencimiento: {due_date.strftime('%Y-%m-%d')}.")
        return invoice, True # Devolver nueva factura, created = True
    except Exception as e:
        logger.error(f"Error al generar factura para la suscripción ID {subscription.pk} (ciclo {cycle_start_date}): {e}")
        return None, False # Error, created = False


def get_due_cycle_start_date_for_subscription(subscription: UserSubscription, as_of_date: date) -> date | None:
    """
    Determina la fecha de inicio del ciclo teóricamente debida para una suscripción en 'as_of_date'.
    No verifica el día de anclaje ni si la factura ya existe.
    """
    if not subscription.is_active:
        return None

    cycle_start_for_invoice = None

    if subscription.billing_cycle == 'once':
        # For 'once', the cycle is the subscription's start_date, if it's on or before as_of_date.
        if subscription.start_date <= as_of_date:
            cycle_start_for_invoice = subscription.start_date
    else: # Recurring cycles
        last_invoice_for_sub = Invoice.objects.filter(user_subscription=subscription).order_by('-cycle_start_date').first()

        next_cycle_start_candidate = None
        if last_invoice_for_sub:
            last_billed_cycle_start = last_invoice_for_sub.cycle_start_date
            if subscription.billing_cycle == 'monthly':
                next_cycle_start_candidate = last_billed_cycle_start + relativedelta(months=1)
            elif subscription.billing_cycle == 'quarterly':
                next_cycle_start_candidate = last_billed_cycle_start + relativedelta(months=3)
            elif subscription.billing_cycle == 'annually':
                next_cycle_start_candidate = last_billed_cycle_start + relativedelta(years=1)
            else: # 'other' or unhandled cycle
                logger.warning(f"Suscripción ID {subscription.pk}: Ciclo '{subscription.billing_cycle}' no manejado para cálculo de próxima fecha. Omitiendo.")
                return None
        else: # No previous invoices, the first cycle is based on subscription start_date
            # Align with anchor day for the month of start_date, or next month if anchor day already passed.
            # This part ensures the candidate is correctly aligned with an anchor day concept for regularity,
            # even if this function doesn't filter by *today's* anchor day.
            if subscription.billing_cycle_anchor_day:
                candidate = subscription.start_date.replace(day=subscription.billing_cycle_anchor_day)
                if candidate < subscription.start_date: # If anchor day in start month made it earlier than start_date
                    candidate += relativedelta(months=1)
                next_cycle_start_candidate = candidate
            else: # No anchor day, just use start_date (less common for recurring)
                next_cycle_start_candidate = subscription.start_date

        if next_cycle_start_candidate and next_cycle_start_candidate <= as_of_date:
            cycle_start_for_invoice = next_cycle_start_candidate

    if not cycle_start_for_invoice:
        return None

    # Final validation against subscription's own lifecycle dates
    if cycle_start_for_invoice < subscription.start_date:
        return None

    if subscription.end_date and cycle_start_for_invoice > subscription.end_date:
        return None

    # If the cycle determined is for a period that has already entirely passed before as_of_date,
    # then it's not "due" for a billing run on as_of_date, unless it's a 'once' payment type.
    if cycle_start_for_invoice and subscription.billing_cycle != 'once':
        cycle_end_date_exclusive = None # The date the next cycle would start
        if subscription.billing_cycle == 'monthly':
            cycle_end_date_exclusive = cycle_start_for_invoice + relativedelta(months=1)
        elif subscription.billing_cycle == 'quarterly':
            cycle_end_date_exclusive = cycle_start_for_invoice + relativedelta(months=3)
        elif subscription.billing_cycle == 'annually':
            cycle_end_date_exclusive = cycle_start_for_invoice + relativedelta(years=1)

        # If the cycle would have ended before or on as_of_date, it's not prospectively due.
        # (e.g. cycle is Mar 1 - Mar 31. If as_of_date is Apr 1, that cycle is no longer "due" for this run)
        if cycle_end_date_exclusive and cycle_end_date_exclusive <= as_of_date:
            logger.debug(f"Suscripción ID {subscription.pk}: Ciclo que inicia en {cycle_start_for_invoice} (termina antes de {cycle_end_date_exclusive}) ya concluyó respecto a {as_of_date}. Omitiendo.")
            return None

    return cycle_start_for_invoice


def generate_all_due_invoices(as_of_date: date = None) -> tuple[int, int, int]:
    """
    Itera sobre todas las suscripciones activas y genera facturas si son debidas
    según su ciclo de facturación y día de anclaje.

    Args:
        as_of_date: La fecha para la cual se está verificando la generación de facturas (default: hoy).

    Returns:
        Un tuple: (newly_generated_count, already_existed_count, failed_or_skipped_count)
    """
    if as_of_date is None:
        as_of_date = timezone.now().date()

    newly_generated_count = 0
    already_existed_count = 0
    failed_or_skipped_count = 0

    active_subscriptions = UserSubscription.objects.filter(is_active=True)
    logger.info(f"Verificando {active_subscriptions.count()} suscripciones activas para facturación con fecha de referencia {as_of_date}...")

    for sub in active_subscriptions:
        if sub.billing_cycle_anchor_day is None:
            logger.info(f"Suscripción ID {sub.pk}: billing_cycle_anchor_day no está configurado. Omitiendo.")
            failed_or_skipped_count += 1
            continue

        if as_of_date.day != sub.billing_cycle_anchor_day:
            # Not the anchor day for this subscription, normal skip, not counted in "failed_or_skipped_count"
            # as this count is for actual processing issues or explicit skips by the logic.
            continue

        cycle_start_to_bill = get_due_cycle_start_date_for_subscription(sub, as_of_date)

        if cycle_start_to_bill:
            logger.info(f"Suscripción ID {sub.pk}: Ciclo debido determinado para {cycle_start_to_bill}. Intentando generar/recuperar factura.")
            invoice, created = generate_invoice_for_subscription(sub, cycle_start_to_bill)
            if invoice:
                if created:
                    newly_generated_count += 1
                    logger.info(f"Factura NUEVA {invoice.invoice_number} generada para Suscripción ID {sub.pk}.")
                else:
                    already_existed_count += 1
                    logger.info(f"Factura {invoice.invoice_number} YA EXISTÍA para Suscripción ID {sub.pk} y ciclo {cycle_start_to_bill}.")
            else: # generate_invoice_for_subscription returned (None, False)
                failed_or_skipped_count += 1
                logger.warning(f"generate_invoice_for_subscription falló o omitió la Suscripción ID {sub.pk} para el ciclo {cycle_start_to_bill}.")
        # else:
            # If get_due_cycle_start_date_for_subscription returns None, it means the subscription is not due for a new cycle yet
            # (e.g., next cycle is in the future, or 'once' already processed implicitly by having an invoice, or inactive).
            # This is a normal operational skip, not counted in failed_or_skipped_count.
            # logger.debug(f"Suscripción ID {sub.pk}: No se determinó un ciclo de facturación debido para {as_of_date} por get_due_cycle_start_date_for_subscription.")
            # pass # Not an error or explicit skip to be counted in summary totals here.

    logger.info(f"Generación de todas las facturas debidas completada. Nuevas: {newly_generated_count}, Ya existentes: {already_existed_count}, Fallidas/Omitidas por gen_inv: {failed_or_skipped_count}")
    return newly_generated_count, already_existed_count, failed_or_skipped_count
