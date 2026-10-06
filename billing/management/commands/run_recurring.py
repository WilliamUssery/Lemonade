"""Create and send invoices for every active schedule that is due today (or earlier).

Run once a day: python manage.py run_recurring
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import RecurringInvoice
from billing.services import InvoiceService


class Command(BaseCommand):
    help = "Create and send invoices for recurring schedules that are due."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List what would be sent, send nothing")

    def handle(self, *args, dry_run=False, **options):
        today = timezone.localdate()
        due = RecurringInvoice.objects.filter(active=True, next_run__lte=today).select_related("client", "business")
        for schedule in due:
            if dry_run:
                self.stdout.write(f"Would invoice {schedule}")
                continue
            try:
                invoice = InvoiceService.run_schedule(schedule, today)
                self.stdout.write(self.style.SUCCESS(f"Sent {invoice.number} to {invoice.client.email}"))
            except ValueError as exc:  # e.g. client no longer linked to the business
                self.stderr.write(f"Skipped {schedule}: {exc}")
