"""Email a reminder for every sent invoice that is overdue.

Usage: python manage.py send_reminders            (3+ days overdue)
       python manage.py send_reminders --days 7
"""
import datetime

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from billing.models import Invoice
from billing.services import InvoiceService


class Command(BaseCommand):
    help = "Send reminder emails for invoices that are overdue."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3, help="Days past the due date (default 3)")

    def handle(self, *args, days, **options):
        cutoff = timezone.localdate() - datetime.timedelta(days=days)
        not_recent = timezone.now() - datetime.timedelta(days=days)
        invoices = Invoice.objects.filter(status=Invoice.Status.SENT, due_date__lte=cutoff).filter(
            Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lt=not_recent)
        )
        count = 0
        for invoice in invoices.select_related("client", "business"):
            InvoiceService.remind(invoice)
            count += 1
            self.stdout.write(f"Reminded {invoice.client.email} about {invoice.number}")
        self.stdout.write(self.style.SUCCESS(f"Sent {count} reminder(s)."))
