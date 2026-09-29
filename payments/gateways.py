"""Payment gateways share one interface. Adding a new method = adding a new class here.

DualLedger never holds or moves money:
  * SquareGateway creates a hosted checkout link on the invoice's business location,
    so card funds settle straight into that business's bank account.
  * ManualGateway shows the business's Zelle / Venmo / Chime handle and records a
    pending payment that Christie confirms from the dashboard.
"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from billing.services import InvoiceService

from .models import Payment


class GatewayError(Exception):
    pass


class PaymentGateway:
    method = None

    def start(self, invoice, **kwargs):
        """Begin a payment. Returns the Payment record."""
        raise NotImplementedError

    @staticmethod
    @transaction.atomic
    def confirm(payment, user=None, external_ref=None):
        """Mark a payment confirmed and the invoice paid (emails the receipt)."""
        payment.status = Payment.Status.CONFIRMED
        payment.confirmed_by = user
        payment.confirmed_at = timezone.now()
        if external_ref:
            payment.external_ref = external_ref
        payment.save()
        # Any other open attempts on this invoice are no longer needed.
        payment.invoice.payments.exclude(pk=payment.pk).filter(status=Payment.Status.PENDING).update(
            status=Payment.Status.REJECTED
        )
        if payment.invoice.status != payment.invoice.Status.PAID:
            InvoiceService.mark_paid(payment.invoice)
        return payment

    @staticmethod
    def reject(payment):
        payment.status = Payment.Status.REJECTED
        payment.save(update_fields=["status"])
        return payment


class ManualGateway(PaymentGateway):
    def __init__(self, method):
        self.method = method

    def instructions(self, invoice):
        return {
            "method": self.method,
            "label": Payment.Method(self.method).label,
            "handle": invoice.business.handle_for(self.method),
            "amount": invoice.subtotal,
            "memo": invoice.number,
        }

    def start(self, invoice, memo=""):
        existing = invoice.payments.filter(method=self.method, status=Payment.Status.PENDING).first()
        if existing:
            return existing
        return Payment.objects.create(
            invoice=invoice,
            method=self.method,
            amount=invoice.subtotal,
            external_ref=memo or invoice.number,
        )


class SquareGateway(PaymentGateway):
    method = Payment.Method.CARD

    @property
    def base_url(self):
        if settings.SQUARE_ENVIRONMENT == "production":
            return "https://connect.squareup.com"
        return "https://connect.squareupsandbox.com"

    def start(self, invoice, redirect_url=""):
        payment = Payment.objects.create(
            invoice=invoice,
            method=self.method,
            amount=invoice.card_total,
            fee=invoice.card_fee,
        )
        if settings.SQUARE_SIMULATE:
            # Local test mode: no Square account needed.
            payment.external_ref = f"sim-{uuid.uuid4().hex[:12]}"
            payment.checkout_url = reverse("payments:simulate", args=[payment.pk])
        else:
            order_id, url = self._create_payment_link(invoice, redirect_url)
            payment.external_ref = order_id
            payment.checkout_url = url
        payment.save(update_fields=["external_ref", "checkout_url"])
        return payment

    def _create_payment_link(self, invoice, redirect_url):
        location_id = invoice.business.square_location_id
        if not location_id:
            raise GatewayError(f"{invoice.business} has no Square location ID configured.")
        cents = int(invoice.card_total * 100)
        body = {
            "idempotency_key": str(uuid.uuid4()),
            "quick_pay": {
                "name": f"{invoice.business.name} — Invoice {invoice.number}",
                "price_money": {"amount": cents, "currency": "USD"},
                "location_id": location_id,
            },
            "payment_note": invoice.number,
        }
        if redirect_url:
            body["checkout_options"] = {"redirect_url": redirect_url}
        data = self._post("/v2/online-checkout/payment-links", body)
        link = data["payment_link"]
        return link["order_id"], link["url"]

    def _post(self, path, body):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {settings.SQUARE_ACCESS_TOKEN}",
                "Content-Type": "application/json",
                "Square-Version": "2025-01-23",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise GatewayError(f"Square error {exc.code}: {exc.read().decode()[:300]}") from exc
        except urllib.error.URLError as exc:
            raise GatewayError(f"Could not reach Square: {exc.reason}") from exc

    # --- Webhooks --------------------------------------------------------
    @staticmethod
    def verify_signature(body: bytes, signature: str) -> bool:
        """Square signs notification_url + raw body with HMAC-SHA256 (base64)."""
        key = settings.SQUARE_WEBHOOK_SIGNATURE_KEY
        if not key or not signature:
            return False
        digest = hmac.new(key.encode(), settings.SQUARE_WEBHOOK_URL.encode() + body, hashlib.sha256).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode(), signature)

    def handle_event(self, event: dict):
        """Confirm the matching card payment when Square reports it COMPLETED."""
        if event.get("type") not in ("payment.created", "payment.updated"):
            return None
        square_payment = event.get("data", {}).get("object", {}).get("payment", {})
        if square_payment.get("status") != "COMPLETED":
            return None
        payment = Payment.objects.filter(
            method=Payment.Method.CARD,
            external_ref=square_payment.get("order_id"),
        ).exclude(status=Payment.Status.CONFIRMED).first()
        if payment is None:
            return None
        return self.confirm(payment, external_ref=square_payment.get("order_id"))
