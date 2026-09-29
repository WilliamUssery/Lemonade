import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from clients.models import Client, ClientBusiness

from .models import Business, Invoice, Service
from .services import InvalidTransition, InvoiceService

TODAY = datetime.date(2026, 9, 26)


def make_fixture():
    cleaning = Business.objects.create(name="Christie's Cleaning", code="CL", zelle_handle="clean@x.com")
    tutoring = Business.objects.create(name="Christie's Tutoring", code="TU", venmo_handle="@tutor")
    deep = Service.objects.create(business=cleaning, name="Deep clean", rate=Decimal("160.00"))
    oven = Service.objects.create(business=cleaning, name="Oven add-on", rate=Decimal("25.00"))
    math = Service.objects.create(business=tutoring, name="Math", rate=Decimal("45.00"), unit="hour")
    sarah = Client.objects.create(first_name="Sarah", last_name="Mitchell", email="sarah@example.com")
    ClientBusiness.objects.create(client=sarah, business=cleaning)
    ClientBusiness.objects.create(client=sarah, business=tutoring)
    return cleaning, tutoring, deep, oven, math, sarah


class InvoiceServiceTests(TestCase):
    def setUp(self):
        self.cleaning, self.tutoring, self.deep, self.oven, self.math, self.sarah = make_fixture()

    def create(self, business=None, items=None):
        business = business or self.cleaning
        items = items or [{"service": self.deep}, {"service": self.oven}]
        return InvoiceService.create_invoice(client=self.sarah, business=business, issue_date=TODAY,
                                             due_date=TODAY + datetime.timedelta(days=14), items=items)

    def test_numbers_are_per_business(self):
        self.assertEqual(self.create().number, "CL-0001")
        self.assertEqual(self.create().number, "CL-0002")
        self.assertEqual(self.create(self.tutoring, [{"service": self.math, "quantity": 2}]).number, "TU-0001")

    def test_totals_and_card_surcharge(self):
        invoice = self.create()
        self.assertEqual(invoice.subtotal, Decimal("185.00"))
        self.assertEqual(invoice.card_fee, Decimal("6.48"))  # 3.5% rounded half-up
        self.assertEqual(invoice.card_total, Decimal("191.48"))

    def test_price_is_copied_at_billing_time(self):
        invoice = self.create()
        self.deep.rate = Decimal("999.00")
        self.deep.save()
        self.assertEqual(invoice.subtotal, Decimal("185.00"))

    def test_service_must_match_business(self):
        with self.assertRaises(ValueError):
            self.create(self.cleaning, [{"service": self.math}])

    def test_client_must_be_linked_to_business(self):
        other = Business.objects.create(name="Other", code="OT")
        with self.assertRaises(ValueError):
            self.create(other, [{"description": "Thing", "unit_price": 10}])

    def test_status_is_one_way(self):
        invoice = self.create()
        InvoiceService.send(invoice)
        self.assertEqual(invoice.status, Invoice.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(invoice.pay_token), mail.outbox[0].body)
        InvoiceService.mark_paid(invoice)
        with self.assertRaises(InvalidTransition):
            InvoiceService.void(invoice)
        with self.assertRaises(InvalidTransition):
            InvoiceService.set_items(invoice, [{"service": self.deep}])


class InvoiceViewTests(TestCase):
    def setUp(self):
        self.cleaning, self.tutoring, self.deep, self.oven, self.math, self.sarah = make_fixture()
        self.user = get_user_model().objects.create_user("christie", password="pw-12345")

    def test_staff_pages_require_login(self):
        for name in ["dashboard:index", "clients:list", "billing:list", "billing:create", "payments:list"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"])

    def test_create_and_send_invoice(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("billing:create"), {
            "client": self.sarah.pk, "business": self.cleaning.pk,
            "issue_date": "2026-09-26", "due_date": "2026-10-10", "message": "Thanks!",
            "items-TOTAL_FORMS": "2", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-service": self.deep.pk, "items-0-quantity": "1",
            "items-1-service": self.oven.pk, "items-1-quantity": "1",
            "send": "1",
        })
        invoice = Invoice.objects.get()
        self.assertRedirects(response, invoice.get_absolute_url())
        self.assertEqual(invoice.status, Invoice.Status.SENT)
        self.assertEqual(invoice.subtotal, Decimal("185.00"))
        self.assertEqual(len(mail.outbox), 1)

    def test_rejects_service_from_other_business(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("billing:create"), {
            "client": self.sarah.pk, "business": self.cleaning.pk,
            "issue_date": "2026-09-26", "due_date": "2026-10-10",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-service": self.math.pk, "items-0-quantity": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
