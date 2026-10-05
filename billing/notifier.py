"""Emails the invoice pay link and the receipt. Uses the console backend in development."""
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


class Notifier:
    @staticmethod
    def _send(subject, template, invoice, **extra):
        context = {
            "invoice": invoice,
            "pay_url": f"{settings.SITE_URL}{invoice.get_pay_url()}",
            **extra,
        }
        body = render_to_string(template, context)
        send_mail(
            subject,
            body,
            invoice.business.email or settings.DEFAULT_FROM_EMAIL,
            [invoice.client.email],
        )

    @classmethod
    def send_invoice(cls, invoice):
        cls._send(
            f"{invoice.business.name} sent you invoice {invoice.number} for ${invoice.subtotal}",
            "emails/invoice.txt",
            invoice,
        )

    @classmethod
    def send_reminder(cls, invoice):
        cls._send(
            f"Reminder: invoice {invoice.number} from {invoice.business.name} is due",
            "emails/reminder.txt",
            invoice,
        )

    @classmethod
    def send_receipt(cls, invoice):
        payment = invoice.payments.filter(status="confirmed").first()
        cls._send(
            f"Receipt for {invoice.number} from {invoice.business.name}",
            "emails/receipt.txt",
            invoice,
            payment=payment,
        )
