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

from .models import Invoice, RecurringInvoice, RecurringItem, add_month
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

    # --- Part 2: CSV export ----------------------------------------------
    def rows(self, response):
        return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    def test_invoice_csv_respects_business_filter(self):
        cl = self.invoice()
        tu = self.invoice(business=self.tutoring, service=self.math)
        PaymentGateway.confirm(ManualGateway("zelle").start(cl), user=self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("billing:export"), {"business": "CL"})
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = self.rows(response)
        self.assertEqual(rows[0][0], "Invoice")
        self.assertEqual([r[0] for r in rows[1:]], [cl.number])
        self.assertEqual(rows[1][-1], "160.00")
        self.assertNotIn(tu.number, response.content.decode())

    def test_payment_csv(self):
        PaymentGateway.confirm(ManualGateway("zelle").start(self.invoice()), user=self.user)
        self.client.force_login(self.user)
        rows = self.rows(self.client.get(reverse("payments:export")))
        self.assertEqual(rows[1][4:8], ["Zelle", "160.00", "0.00", "Confirmed"])

    def test_exports_require_login(self):
        for name in ["billing:export", "payments:export"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    # --- Part 3: reminders -----------------------------------------------
    def test_reminder_email_has_pay_link(self):
        inv = self.invoice()
        mail.outbox.clear()
        InvoiceService.remind(inv)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(inv.pay_token), mail.outbox[0].body)
        self.assertIsNotNone(Invoice.objects.get(pk=inv.pk).last_reminded_at)

    def test_cannot_remind_draft_or_paid(self):
        with self.assertRaises(InvalidTransition):
            InvoiceService.remind(self.invoice(send=False))
        paid = self.invoice()
        PaymentGateway.confirm(ManualGateway("zelle").start(paid), user=self.user)
        with self.assertRaises(InvalidTransition):
            InvoiceService.remind(Invoice.objects.get(pk=paid.pk))

    def test_send_reminders_command_skips_recent_and_not_late(self):
        late = self.invoice(due_in_days=-5)
        self.invoice(due_in_days=-1)  # only 1 day late
        mail.outbox.clear()
        call_command("send_reminders", stdout=io.StringIO())
        self.assertEqual([m.to for m in mail.outbox], [[self.sarah.email]])
        self.assertIn(late.number, mail.outbox[0].subject)
        call_command("send_reminders", stdout=io.StringIO())  # just reminded: no repeat
        self.assertEqual(len(mail.outbox), 1)

    # --- Part 5: recurring -----------------------------------------------
    def schedule(self, **kw):
        s = RecurringInvoice.objects.create(client=self.sarah, business=self.cleaning,
                                            next_run=self.today, **kw)
        RecurringItem.objects.create(schedule=s, service=self.deep, quantity=1)
        return s

    def test_run_recurring_creates_one_invoice_and_advances(self):
        s = self.schedule()
        call_command("run_recurring", stdout=io.StringIO())
        inv = Invoice.objects.get()
        self.assertEqual(inv.status, Invoice.Status.SENT)
        self.assertEqual(inv.subtotal, Decimal("160.00"))
        s.refresh_from_db()
        self.assertEqual(s.next_run, self.today + datetime.timedelta(weeks=1))
        call_command("run_recurring", stdout=io.StringIO())  # not due again yet
        self.assertEqual(Invoice.objects.count(), 1)

    def test_paused_schedule_is_skipped(self):
        self.schedule(active=False)
        call_command("run_recurring", stdout=io.StringIO())
        self.assertEqual(Invoice.objects.count(), 0)

    def test_add_month_clamps_to_month_end(self):
        self.assertEqual(add_month(datetime.date(2026, 1, 31)), datetime.date(2026, 2, 28))
        self.assertEqual(add_month(datetime.date(2026, 12, 15)), datetime.date(2027, 1, 15))
