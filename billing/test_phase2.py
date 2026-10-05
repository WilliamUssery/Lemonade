import csv
import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from payments.gateways import ManualGateway, PaymentGateway

from .models import Invoice
from .services import InvalidTransition, InvoiceService
from .tests import make_fixture


class Phase2Tests(TestCase):
    def setUp(self):
        self.cleaning, self.tutoring, self.deep, self.oven, self.math, self.sarah = make_fixture()
        self.user = get_user_model().objects.create_user("christie", password="pw-12345")
        self.today = timezone.localdate()

    def invoice(self, due_in_days=14, send=True, business=None, service=None):
        inv = InvoiceService.create_invoice(
            client=self.sarah, business=business or self.cleaning, issue_date=self.today,
            due_date=self.today + datetime.timedelta(days=due_in_days),
            items=[{"service": service or self.deep}])
        if send:
            InvoiceService.send(inv)
        return inv

    # --- Part 1: overdue -------------------------------------------------
    def test_overdue_only_when_sent_and_past_due(self):
        self.assertTrue(self.invoice(due_in_days=-1).is_overdue)
        self.assertFalse(self.invoice(due_in_days=0).is_overdue)
        self.assertFalse(self.invoice(due_in_days=-1, send=False).is_overdue)  # draft
        self.assertEqual(self.invoice(due_in_days=-1).status_label, "Overdue")

    def test_overdue_filter_on_list(self):
        late = self.invoice(due_in_days=-3)
        on_time = self.invoice(due_in_days=3)
        self.client.force_login(self.user)
        response = self.client.get(reverse("billing:list"), {"status": "overdue"})
        self.assertContains(response, late.number)
        self.assertNotContains(response, on_time.number)
