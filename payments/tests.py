import base64
import datetime
import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import Invoice
from billing.services import InvoiceService
from billing.tests import TODAY, make_fixture

from .gateways import ManualGateway, SquareGateway
from .models import Payment
from .router import MethodNotAccepted, PaymentRouter

WEBHOOK_KEY = "test-signature-key"
WEBHOOK_URL = "https://example.com/payments/square/webhook/"


class PaymentFlowTests(TestCase):
    def setUp(self):
        self.cleaning, self.tutoring, self.deep, self.oven, self.math, self.sarah = make_fixture()
        self.invoice = InvoiceService.create_invoice(
            client=self.sarah, business=self.cleaning, issue_date=TODAY,
            due_date=TODAY + datetime.timedelta(days=14), items=[{"service": self.deep}, {"service": self.oven}])
        InvoiceService.send(self.invoice)
        self.user = get_user_model().objects.create_user("christie", password="pw-12345")

    # --- Router ----------------------------------------------------------
    def test_router_picks_gateway_by_method(self):
        self.assertIsInstance(PaymentRouter.get_gateway(self.invoice, "card"), SquareGateway)
        self.assertIsInstance(PaymentRouter.get_gateway(self.invoice, "zelle"), ManualGateway)

    def test_router_refuses_methods_business_does_not_accept(self):
        with self.assertRaises(MethodNotAccepted):
            PaymentRouter.get_gateway(self.invoice, "venmo")  # Cleaning only has Zelle + card

    # --- Pay page --------------------------------------------------------
    def test_pay_page_is_public_and_shows_only_accepted_methods(self):
        response = self.client.get(self.invoice.get_pay_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "$185.00")
        self.assertContains(response, "Zelle")
        self.assertNotContains(response, "Venmo")

    def test_draft_invoice_pay_link_is_hidden(self):
        draft = InvoiceService.create_invoice(client=self.sarah, business=self.cleaning, issue_date=TODAY,
                                              due_date=TODAY, items=[{"service": self.deep}])
        self.assertEqual(self.client.get(draft.get_pay_url()).status_code, 404)

    def test_manual_payment_then_owner_confirms(self):
        url = reverse("portal:start", args=[self.invoice.pay_token])
        self.client.post(url, {"method": "zelle", "memo": "Sarah M"})
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.amount, self.invoice.subtotal)

        self.client.force_login(self.user)
        self.client.post(reverse("payments:confirm", args=[payment.pk]))
        payment.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.confirmed_by, self.user)
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertIn("Receipt", mail.outbox[-1].subject)

    def test_confirm_requires_login(self):
        payment = ManualGateway("zelle").start(self.invoice)
        response = self.client.post(reverse("payments:confirm", args=[payment.pk]))
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    @override_settings(SQUARE_SIMULATE=True)
    def test_card_payment_adds_surcharge(self):
        response = self.client.post(reverse("portal:start", args=[self.invoice.pay_token]), {"method": "card"})
        payment = Payment.objects.get()
        self.assertRedirects(response, reverse("payments:simulate", args=[payment.pk]))
        self.assertEqual(str(payment.amount), "191.48")
        self.assertEqual(str(payment.fee), "6.48")

    # --- Square webhook --------------------------------------------------
    def _signed_post(self, body):
        raw = json.dumps(body).encode()
        sig = base64.b64encode(hmac.new(WEBHOOK_KEY.encode(), WEBHOOK_URL.encode() + raw, hashlib.sha256).digest())
        return self.client.post(reverse("payments:square_webhook"), raw, content_type="application/json",
                                HTTP_X_SQUARE_HMACSHA256_SIGNATURE=sig.decode())

    @override_settings(SQUARE_WEBHOOK_SIGNATURE_KEY=WEBHOOK_KEY, SQUARE_WEBHOOK_URL=WEBHOOK_URL)
    def test_webhook_confirms_card_payment(self):
        payment = Payment.objects.create(invoice=self.invoice, method="card", amount=self.invoice.card_total,
                                         fee=self.invoice.card_fee, external_ref="ORDER123")
        event = {"type": "payment.updated",
                 "data": {"object": {"payment": {"status": "COMPLETED", "order_id": "ORDER123"}}}}
        self.assertEqual(self._signed_post(event).status_code, 200)
        payment.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)

    @override_settings(SQUARE_WEBHOOK_SIGNATURE_KEY=WEBHOOK_KEY, SQUARE_WEBHOOK_URL=WEBHOOK_URL)
    def test_webhook_rejects_bad_signature(self):
        response = self.client.post(reverse("payments:square_webhook"), b"{}", content_type="application/json",
                                    HTTP_X_SQUARE_HMACSHA256_SIGNATURE="forged")
        self.assertEqual(response.status_code, 403)
