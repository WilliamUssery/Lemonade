import calendar
import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class Business(models.Model):
    """One of Christie's businesses. Each has its own rates, handles and Square location."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=4, unique=True, help_text="Invoice prefix, e.g. CL or TU")
    color = models.CharField(max_length=7, default="#0E9F8E", help_text="Hex color used in the UI")
    email = models.EmailField(blank=True)

    # Payment settings
    square_location_id = models.CharField(max_length=64, blank=True)
    accepts_card = models.BooleanField(default=True)
    venmo_handle = models.CharField(max_length=64, blank=True)
    zelle_handle = models.CharField(max_length=128, blank=True)
    chime_handle = models.CharField(max_length=64, blank=True)

    next_invoice_number = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "businesses"

    def __str__(self):
        return self.name

    def accepted_methods(self):
        """Payment methods this business accepts, in display order."""
        from payments.models import Payment

        methods = []
        if self.accepts_card:
            methods.append(Payment.Method.CARD)
        if self.zelle_handle:
            methods.append(Payment.Method.ZELLE)
        if self.venmo_handle:
            methods.append(Payment.Method.VENMO)
        if self.chime_handle:
            methods.append(Payment.Method.CHIME)
        return methods

    def handle_for(self, method):
        return {
            "venmo": self.venmo_handle,
            "zelle": self.zelle_handle,
            "chime": self.chime_handle,
        }.get(method, "")


class Service(models.Model):
    class Unit(models.TextChoices):
        VISIT = "visit", "per visit"
        HOUR = "hour", "per hour"
        SESSION = "session", "per session"
        FLAT = "flat", "flat"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=120)
    rate = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.VISIT)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["business__name", "name"]

    def __str__(self):
        return f"{self.name} (${self.rate} {self.get_unit_display()})"


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    # Allowed one-way status transitions.
    TRANSITIONS = {
        Status.DRAFT: {Status.SENT, Status.VOID},
        Status.SENT: {Status.PAID, Status.VOID},
        Status.PAID: set(),
        Status.VOID: set(),
    }

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="invoices")
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=16, unique=True, editable=False)
    status = models.CharField(max_length=5, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField()
    message = models.TextField(blank=True, help_text="Optional note shown to the client")
    pay_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issue_date", "-id"]

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("billing:detail", args=[self.pk])

    def get_pay_url(self):
        return reverse("portal:pay", args=[self.pay_token])

    @property
    def subtotal(self):
        return money(sum((item.amount for item in self.items.all()), Decimal("0")))

    @property
    def card_fee(self):
        return money(self.subtotal * Decimal(settings.CARD_SURCHARGE_RATE))

    @property
    def card_total(self):
        return self.subtotal + self.card_fee

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    @property
    def is_overdue(self):
        return self.status == self.Status.SENT and self.due_date < timezone.localdate()

    @property
    def status_key(self):
        """CSS key for the status pill; 'overdue' wins over 'sent'."""
        return "overdue" if self.is_overdue else self.status

    @property
    def status_label(self):
        return "Overdue" if self.is_overdue else self.get_status_display()

    @property
    def is_payable(self):
        return self.status == self.Status.SENT

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS[self.status]


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=7, decimal_places=2, default=1,
                                   validators=[MinValueValidator(Decimal("0.01"))])
    # Copied from the service at billing time so later rate changes don't alter old invoices.
    unit_price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])

    def __str__(self):
        return self.description

    @property
    def amount(self):
        return money(self.quantity * self.unit_price)


def add_month(day):
    """Same day next month, clamped to the month's last day (Jan 31 -> Feb 28)."""
    year, month = day.year + day.month // 12, day.month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


class RecurringInvoice(models.Model):
    """A schedule that creates and sends the same invoice on a regular basis."""

    class Frequency(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        BIWEEKLY = "biweekly", "Every 2 weeks"
        MONTHLY = "monthly", "Monthly"

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="schedules")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="schedules")
    frequency = models.CharField(max_length=8, choices=Frequency.choices, default=Frequency.WEEKLY)
    next_run = models.DateField(help_text="Date the next invoice is created and sent")
    days_until_due = models.PositiveIntegerField(default=7)
    message = models.TextField(blank=True, help_text="Optional note shown to the client")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_run"]

    def __str__(self):
        return f"{self.client} · {self.business} · {self.get_frequency_display()}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.client_id and self.business_id and not self.client.businesses.filter(pk=self.business_id).exists():
            raise ValidationError(f"{self.client} is not a client of {self.business}.")

    def advance(self):
        if self.frequency == self.Frequency.WEEKLY:
            self.next_run += datetime.timedelta(weeks=1)
        elif self.frequency == self.Frequency.BIWEEKLY:
            self.next_run += datetime.timedelta(weeks=2)
        else:
            self.next_run = add_month(self.next_run)
        self.save(update_fields=["next_run"])


class RecurringItem(models.Model):
    schedule = models.ForeignKey(RecurringInvoice, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=7, decimal_places=2, default=1,
                                   validators=[MinValueValidator(Decimal("0.01"))])

    def __str__(self):
        return f"{self.service.name} x {self.quantity}"
