from django import forms

from billing.models import Business

from .models import Client, ClientBusiness


class ClientForm(forms.ModelForm):
    business_links = forms.ModelMultipleChoiceField(
        queryset=Business.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        label="Businesses",
        help_text="Which of Christie's businesses this client uses.",
    )

    class Meta:
        model = Client
        fields = ["first_name", "last_name", "email", "phone", "address", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["business_links"].initial = self.instance.businesses.all()

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        digits = "".join(ch for ch in self.cleaned_data.get("phone", "") if ch.isdigit())
        if not digits:
            return ""
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            raise forms.ValidationError("Enter a 10-digit US phone number.")
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    def save(self, commit=True):
        client = super().save(commit=commit)
        if commit:
            selected = set(self.cleaned_data["business_links"])
            current = set(client.businesses.all())
            for business in selected - current:
                ClientBusiness.objects.create(client=client, business=business)
            ClientBusiness.objects.filter(client=client, business__in=current - selected).delete()
        return client
