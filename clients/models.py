from django.db import models
from django.urls import reverse


class Client(models.Model):
    """A client is stored once, then linked to one or both businesses."""

    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    businesses = models.ManyToManyField("billing.Business", through="ClientBusiness", related_name="clients")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def initials(self):
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()

    def get_absolute_url(self):
        return reverse("clients:detail", args=[self.pk])


class ClientBusiness(models.Model):
    """Link table that makes the customer database unified across businesses."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    business = models.ForeignKey("billing.Business", on_delete=models.CASCADE)
    since = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ("client", "business")
        verbose_name = "client–business link"

    def __str__(self):
        return f"{self.client} ↔ {self.business}"
