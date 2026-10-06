"""Business logic for invoices, kept out of views so it can be tested directly."""
import datetime

from django.db import transaction
from django.utils import timezone

from .models import Business, Invoice, InvoiceItem


class InvalidTransition(Exception):
    pass


class InvoiceService:
    @staticmethod
    def next_number(business):
        """Reserve the next per-business invoice number, e.g. CL-0001 or TU-0001."""
        with transaction.atomic():
            locked = Business.objects.select_for_update().get(pk=business.pk)
            number = f"{locked.code}-{locked.next_invoice_number:04d}"
            locked.next_invoice_number += 1
            locked.save(update_fields=["next_invoice_number"])
        business.next_invoice_number = locked.next_invoice_number
        return number

    @classmethod
    @transaction.atomic
    def create_invoice(cls, *, client, business, issue_date, due_date, items, message="", user=None):
        """Create an invoice with its line items.

        `items` is a list of dicts: {"service", "description", "quantity", "unit_price"}.
        If unit_price is missing, the service's current rate is copied in.
        """
        if not client.businesses.filter(pk=business.pk).exists():
            raise ValueError(f"{client} is not a client of {business}.")
        if not items:
            raise ValueError("An invoice needs at least one line item.")

        invoice = Invoice.objects.create(
            business=business,
            client=client,
            number=cls.next_number(business),
            issue_date=issue_date,
            due_date=due_date,
            message=message,
            created_by=user,
        )
        cls.set_items(invoice, items)
        return invoice

    @staticmethod
    def set_items(invoice, items):
        if not invoice.is_editable:
            raise InvalidTransition("Only draft invoices can be edited.")
        invoice.items.all().delete()
        for item in items:
            service = item.get("service")
            if service is not None and service.business_id != invoice.business_id:
                raise ValueError(f"{service.name} does not belong to {invoice.business}.")
            InvoiceItem.objects.create(
                invoice=invoice,
                service=service,
                description=item.get("description") or (service.name if service else ""),
                quantity=item.get("quantity", 1),
                unit_price=item.get("unit_price") if item.get("unit_price") is not None else service.rate,
            )

    @staticmethod
    def transition(invoice, new_status):
        if not invoice.can_transition_to(new_status):
            raise InvalidTransition(
                f"Cannot move {invoice.number} from {invoice.get_status_display()} "
                f"to {Invoice.Status(new_status).label}."
            )
        invoice.status = new_status
        fields = ["status"]
        if new_status == Invoice.Status.SENT:
            invoice.sent_at = timezone.now()
            fields.append("sent_at")
        elif new_status == Invoice.Status.PAID:
            invoice.paid_at = timezone.now()
            fields.append("paid_at")
        invoice.save(update_fields=fields)
        return invoice

    @classmethod
    def send(cls, invoice):
        from .notifier import Notifier

        cls.transition(invoice, Invoice.Status.SENT)
        Notifier.send_invoice(invoice)
        return invoice

    @classmethod
    def resend(cls, invoice):
        from .notifier import Notifier

        if invoice.status != Invoice.Status.SENT:
            raise InvalidTransition("Only sent, unpaid invoices can be resent.")
        Notifier.send_invoice(invoice)
        return invoice

    @classmethod
    def remind(cls, invoice):
        from .notifier import Notifier

        if invoice.status != Invoice.Status.SENT:
            raise InvalidTransition("Only sent, unpaid invoices can get a reminder.")
        Notifier.send_reminder(invoice)
        invoice.last_reminded_at = timezone.now()
        invoice.save(update_fields=["last_reminded_at"])
        return invoice

    @classmethod
    def void(cls, invoice):
        return cls.transition(invoice, Invoice.Status.VOID)

    @classmethod
    @transaction.atomic
    def run_schedule(cls, schedule, today):
        """Create and send one invoice from a RecurringInvoice, then move it to the next date.
        Prices come from each service's current rate."""
        invoice = cls.create_invoice(
            client=schedule.client,
            business=schedule.business,
            issue_date=today,
            due_date=today + datetime.timedelta(days=schedule.days_until_due),
            items=[{"service": i.service, "quantity": i.quantity} for i in schedule.items.all()],
            message=schedule.message,
        )
        cls.send(invoice)
        schedule.advance()
        return invoice

    @classmethod
    def mark_paid(cls, invoice):
        from .notifier import Notifier

        cls.transition(invoice, Invoice.Status.PAID)
        Notifier.send_receipt(invoice)
        return invoice
