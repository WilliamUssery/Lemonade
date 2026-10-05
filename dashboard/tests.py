import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.services import InvoiceService
from billing.tests import make_fixture
from payments.gateways import ManualGateway, PaymentGateway


class DashboardTests(TestCase):
    def setUp(self):
        self.cleaning, self.tutoring, self.deep, self.oven, self.math, self.sarah = make_fixture()
        self.user = get_user_model().objects.create_user("christie", password="pw-12345")
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def invoice(self, business, service, due_in_days):
        inv = InvoiceService.create_invoice(
            client=self.sarah, business=business, issue_date=self.today,
            due_date=self.today + datetime.timedelta(days=due_in_days), items=[{"service": service}])
        InvoiceService.send(inv)
        return inv

    def test_monthly_totals_per_business(self):
        paid = self.invoice(self.cleaning, self.deep, 14)
        PaymentGateway.confirm(ManualGateway("zelle").start(paid), user=self.user)
        self.invoice(self.tutoring, self.math, 14)  # sent, not paid
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.context["collected"], Decimal("160.00"))
        totals = {row["business"].code: row["amount"] for row in response.context["by_business"]}
        self.assertEqual(totals, {"CL": Decimal("160.00"), "TU": Decimal("0")})

    def test_overdue_count_and_total(self):
        self.invoice(self.cleaning, self.deep, -5)  # overdue
        self.invoice(self.tutoring, self.math, 7)  # not yet due
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertEqual(response.context["overdue_total"], Decimal("160.00"))
        self.assertContains(response, "1 overdue")
