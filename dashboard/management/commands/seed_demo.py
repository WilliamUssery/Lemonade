"""Load realistic demo data: python manage.py seed_demo  (add --reset to wipe first)."""
import datetime
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import Business, Invoice, Service
from billing.services import InvoiceService
from clients.models import Client, ClientBusiness
from payments.gateways import ManualGateway, PaymentGateway, SquareGateway
from payments.models import Payment

CLIENTS = [
    ("Sarah", "Mitchell", "(478) 555-0142", "112 Pine Ridge Dr, Gray, GA", ["CL", "TU"],
     "Bi-weekly deep clean, has a dog (key under mat). Son Ethan — Algebra I tutoring Tue/Thu 4 pm."),
    ("Maya", "Patel", "(478) 555-0187", "45 Oakview Ln, Macon, GA", ["TU"], "SAT math prep, Saturdays."),
    ("David", "Okafor", "(478) 555-0119", "830 Forsyth Rd, Macon, GA", ["CL"], "Move-out clean for rental units."),
    ("Linda", "Brooks", "(478) 555-0166", "19 Hunt Cir, Gray, GA", ["CL"], ""),
    ("James", "Carter", "(478) 555-0103", "2201 Vineville Ave, Macon, GA", ["TU"], "Chemistry, twice a week."),
    ("Angela", "Reyes", "(478) 555-0150", "7 Magnolia Ct, Gray, GA", ["CL", "TU"], "Weekly clean + reading tutoring for Sofia."),
    ("Kevin", "Nguyen", "(478) 555-0134", "58 Walnut St, Macon, GA", ["CL"], ""),
    ("Tasha", "Greene", "(478) 555-0178", "311 Cherry St, Macon, GA", ["TU"], "Essay writing help."),
]

SERVICES = {
    "CL": [("Standard clean — 2 bed / 1 bath", "120.00", "visit"), ("Deep clean — 3 bed / 2 bath", "160.00", "visit"),
           ("Move-out clean", "240.00", "visit"), ("Inside oven add-on", "25.00", "flat"),
           ("Inside fridge add-on", "25.00", "flat")],
    "TU": [("Math tutoring (K-12)", "45.00", "hour"), ("SAT / ACT prep", "60.00", "hour"),
           ("Reading & writing", "40.00", "hour"), ("Chemistry tutoring", "50.00", "hour")],
}


class Command(BaseCommand):
    help = "Create demo businesses, services, clients, invoices and payments."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing data first")

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        random.seed(7)
        if reset:
            Payment.objects.all().delete()
            Invoice.objects.all().delete()
            Client.objects.all().delete()
            Service.objects.all().delete()
            Business.objects.all().delete()

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username="christie", defaults={"first_name": "Christie", "last_name": "Flowers",
                                           "email": "christie@example.com", "is_staff": True, "is_superuser": True})
        if created:
            user.set_password("dualledger123")
            user.save()

        cleaning, _ = Business.objects.update_or_create(code="CL", defaults=dict(
            name="Christie's Cleaning", color="#0E9F8E", email="clean@example.com", accepts_card=True,
            square_location_id="L_SANDBOX_CLEANING", zelle_handle="christie.clean@gmail.com",
            venmo_handle="@ChristieCleans"))
        tutoring, _ = Business.objects.update_or_create(code="TU", defaults=dict(
            name="Christie's Tutoring", color="#6D5BD0", email="tutor@example.com", accepts_card=True,
            square_location_id="L_SANDBOX_TUTORING", zelle_handle="christie.tutors@gmail.com",
            venmo_handle="@ChristieTutors", chime_handle="$ChristieTutors"))
        biz = {"CL": cleaning, "TU": tutoring}

        for code, rows in SERVICES.items():
            for name, rate, unit in rows:
                Service.objects.update_or_create(business=biz[code], name=name,
                                                 defaults={"rate": Decimal(rate), "unit": unit})

        clients = []
        for first, last, phone, addr, codes, notes in CLIENTS:
            c, _ = Client.objects.update_or_create(
                email=f"{first}.{last}@gmail.com".lower(),
                defaults=dict(first_name=first, last_name=last, phone=phone, address=addr, notes=notes))
            for code in codes:
                ClientBusiness.objects.get_or_create(client=c, business=biz[code])
            Client.objects.filter(pk=c.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=random.randint(120, 540)))
            clients.append((c, codes))

        if Invoice.objects.exists():
            self.stdout.write(self.style.WARNING("Invoices already exist — skipped. Use --reset to rebuild."))
            return

        today = timezone.localdate()
        now = timezone.now()
        mail.outbox = []  # keep demo emails out of the console
        self._quiet_mail()

        # ~3 months of history, oldest first so invoice numbers ascend with dates.
        plan = []
        for days_ago in range(84, -1, -2):
            client, codes = random.choice(clients)
            plan.append((days_ago, client, random.choice(codes)))

        for i, (days_ago, client, code) in enumerate(plan):
            business = biz[code]
            services = list(business.services.all())
            svc = random.choice(services[:3] if code == "CL" else services)
            items = [{"service": svc, "quantity": 1 if code == "CL" else Decimal(random.choice(["1", "1.5", "2"]))}]
            if code == "CL" and random.random() < .3:
                items.append({"service": business.services.get(name="Inside oven add-on"), "quantity": 1})
            issued = today - datetime.timedelta(days=days_ago)
            inv = InvoiceService.create_invoice(client=client, business=business, issue_date=issued,
                                                due_date=issued + datetime.timedelta(days=14), items=items, user=user)
            Invoice.objects.filter(pk=inv.pk).update(created_at=now - datetime.timedelta(days=days_ago))

            if days_ago <= 2 and i % 2:
                continue  # leave a couple as drafts
            InvoiceService.send(inv)
            if days_ago <= 9 and random.random() < .5:
                continue  # recent ones still open

            method = random.choice([m for m in business.accepted_methods()])
            if days_ago <= 12 and method != "card":
                ManualGateway(method).start(inv)  # waiting on Christie
                continue
            gateway = SquareGateway() if method == "card" else ManualGateway(method)
            payment = gateway.start(inv)
            PaymentGateway.confirm(payment, user=None if method == "card" else user)
            when = now - datetime.timedelta(days=max(days_ago - random.randint(1, 5), 0))
            Payment.objects.filter(pk=payment.pk).update(confirmed_at=when, created_at=when)
            Invoice.objects.filter(pk=inv.pk).update(paid_at=when, sent_at=now - datetime.timedelta(days=days_ago))

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready: {Client.objects.count()} clients, {Invoice.objects.count()} invoices, "
            f"{Payment.objects.count()} payments.\nLog in as christie / dualledger123"))

    @staticmethod
    def _quiet_mail():
        from django.conf import settings
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
