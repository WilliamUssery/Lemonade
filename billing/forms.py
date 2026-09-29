import datetime

from django import forms
from django.utils import timezone

from clients.models import Client

from .models import Business, Service


class InvoiceForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.all())
    business = forms.ModelChoiceField(queryset=Business.objects.all(), widget=forms.RadioSelect, empty_label=None)
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    message = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                              label="Message to client")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["issue_date"].initial = today
        self.fields["due_date"].initial = today + datetime.timedelta(days=14)

    def clean(self):
        data = super().clean()
        client, business = data.get("client"), data.get("business")
        if client and business and not client.businesses.filter(pk=business.pk).exists():
            self.add_error("business", f"{client} is not linked to {business}. Edit the client first.")
        if data.get("issue_date") and data.get("due_date") and data["due_date"] < data["issue_date"]:
            self.add_error("due_date", "Due date can't be before the issue date.")
        return data


class InvoiceItemForm(forms.Form):
    service = forms.ModelChoiceField(queryset=Service.objects.filter(active=True).select_related("business"),
                                     required=False)
    description = forms.CharField(max_length=200, required=False)
    quantity = forms.DecimalField(min_value=0.01, decimal_places=2, initial=1)
    unit_price = forms.DecimalField(min_value=0, decimal_places=2, required=False,
                                    help_text="Leave blank to use the service rate")

    def clean(self):
        data = super().clean()
        if not data.get("service") and not data.get("description"):
            raise forms.ValidationError("Pick a service or type a description.")
        if not data.get("service") and data.get("unit_price") is None:
            self.add_error("unit_price", "Custom items need a price.")
        return data


class BaseItemFormSet(forms.BaseFormSet):
    def __init__(self, *args, business=None, **kwargs):
        self.business = business
        super().__init__(*args, **kwargs)

    def clean(self):
        if any(self.errors):
            return
        items = [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not items:
            raise forms.ValidationError("Add at least one line item.")
        if self.business:
            for item in items:
                service = item.get("service")
                if service and service.business_id != self.business.pk:
                    raise forms.ValidationError(f"“{service.name}” belongs to {service.business}, not {self.business}.")

    def items(self):
        return [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]


InvoiceItemFormSet = forms.formset_factory(InvoiceItemForm, formset=BaseItemFormSet, extra=0, min_num=1,
                                           can_delete=True)
