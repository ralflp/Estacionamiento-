import logging
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone
from log_viewer_app.models import UserSubscription # Added for the final 'no active subscriptions' check
from log_viewer_app.billing_utils import generate_all_due_invoices
# generate_invoice_for_subscription is no longer directly used by the command.
# date from datetime is no longer directly used by the command.

logger = logging.getLogger(__name__) # logging import was missing, added it.

class Command(BaseCommand):
    help = 'Generates facturas periódicas para suscripciones activas basadas en su día de anclaje de facturación.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Iniciando generación de facturas periódicas..."))
        today = timezone.now().date() # Usar la fecha actual para la ejecución del comando

        new_count, existing_count, failed_count = generate_all_due_invoices(as_of_date=today)

        if new_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Se generaron {new_count} nueva(s) factura(s)."))
        if existing_count > 0:
            self.stdout.write(self.style.NOTICE(f"{existing_count} factura(s) ya existían para el ciclo actual y fueron omitidas."))
        if failed_count > 0:
            self.stdout.write(self.style.WARNING(f"{failed_count} suscripciones fueron omitidas o fallaron durante la generación (ver logs para detalles)."))

        # Check if any processing happened at all, or if it was just a day with no anchor matches
        # total_processed_or_evaluated_by_util = new_count + existing_count + failed_count
        # The failed_count in generate_all_due_invoices includes actual processing skips/failures,
        # not just subscriptions whose anchor day isn't today.

        # If the utility function ran and found nothing to do (e.g. no subscriptions matched anchor day or were due)
        # it will return (0,0,0) if it iterated through some subscriptions but none resulted in action.
        # The logger inside generate_all_due_invoices gives total active subs.
        # This command's output should be meaningful if nothing was done.

        if new_count == 0 and existing_count == 0 and failed_count == 0:
            # This means generate_all_due_invoices either found no active subscriptions,
            # or none of them had today as their anchor day, or none were actually due for a new cycle.
            active_subscriptions_count = UserSubscription.objects.filter(is_active=True).count()
            if active_subscriptions_count == 0:
                self.stdout.write(self.style.SUCCESS("No hay suscripciones activas para facturar."))
            else:
                # This implies active subscriptions exist, but none were due for processing today by generate_all_due_invoices
                self.stdout.write(self.style.SUCCESS("No hay facturas debidas para generar en este momento según los días de anclaje y ciclos."))

        self.stdout.write(self.style.SUCCESS("Proceso de generación de facturas periódicas completado."))
