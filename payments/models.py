from django.conf import settings
from django.db import models


class Payment(models.Model):
    """A payment against one invoice. DualLedger records payments; it never holds money."""

    class Method(models.TextChoices):
        CARD = "card", "Card (Square)"
        ZELLE = "zelle", "Zelle"
        VENMO = "venmo", "Venmo"
        CHIME = "chime", "Chime"

    MANUAL_METHODS = {Method.ZELLE, Method.VENMO, Method.CHIME}

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    invoice = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=5, choices=Method.choices)
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    # Square order/payment ID, or the Zelle/Venmo/Chime memo the client used.
    external_ref = models.CharField(max_length=128, blank=True, db_index=True)
    checkout_url = models.URLField(max_length=500, blank=True)

    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invoice.number} · {self.get_method_display()} · ${self.amount}"

    @property
    def is_manual(self):
        return self.method in self.MANUAL_METHODS
