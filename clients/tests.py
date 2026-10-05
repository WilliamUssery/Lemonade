from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from billing.tests import make_fixture

from .forms import ClientForm
from .models import Client


class ClientTests(TestCase):
    def setUp(self):
        self.cleaning, self.tutoring, *_, self.sarah = make_fixture()
        self.sarah.phone = "(478) 555-0142"
        self.sarah.save()
        self.user = get_user_model().objects.create_user("christie", password="pw-12345")

    def form(self, **overrides):
        data = {"first_name": "Sara", "last_name": "Mitch", "email": "new@example.com",
                "phone": "", "business_links": [self.cleaning.pk], **overrides}
        return ClientForm(data)

    def test_same_phone_warns(self):
        form = self.form(phone="478-555-0142")
        self.assertFalse(form.is_valid())
        self.assertEqual(form.duplicates, [self.sarah])

    def test_same_name_warns(self):
        form = self.form(first_name="sarah", last_name="MITCHELL")
        self.assertFalse(form.is_valid())

    def test_save_anyway_saves(self):
        form = self.form(phone="478-555-0142", confirm_duplicate="on")
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(Client.objects.count(), 2)

    def test_editing_a_client_does_not_flag_itself(self):
        form = ClientForm({"first_name": "Sarah", "last_name": "Mitchell", "email": "sarah@example.com",
                           "phone": "(478) 555-0142", "business_links": [self.cleaning.pk]},
                          instance=self.sarah)
        self.assertTrue(form.is_valid(), form.errors)

    def test_search_by_name_and_business(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("clients:list"), {"q": "mitch", "business": "TU"})
        self.assertContains(response, "Sarah Mitchell")
        response = self.client.get(reverse("clients:list"), {"q": "nobody"})
        self.assertNotContains(response, "Sarah Mitchell")
