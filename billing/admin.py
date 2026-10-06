from django.contrib import admin

from payments.models import Payment

from .models import Business, Invoice, InvoiceItem, RecurringInvoice, RecurringItem, Service


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 0


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "accepts_card", "zelle_handle", "venmo_handle", "chime_handle",
                    "next_invoice_number")
    readonly_fields = ("next_invoice_number",)
    inlines = [ServiceInline]
    fieldsets = (
        (None, {"fields": ("name", "code", "color", "email", "next_invoice_number")}),
        ("Payments", {"fields": ("accepts_card", "square_location_id", "zelle_handle", "venmo_handle",
                                 "chime_handle")}),
    )


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "rate", "unit", "active")
    list_filter = ("business", "active", "unit")
    list_editable = ("rate", "active")
    search_fields = ("name",)


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("created_at", "confirmed_at", "confirmed_by")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "client", "business", "status", "issue_date", "due_date", "subtotal")
    list_filter = ("business", "status")
    search_fields = ("number", "client__first_name", "client__last_name", "client__email")
    readonly_fields = ("number", "pay_token", "created_by", "created_at", "sent_at", "paid_at")
    date_hierarchy = "issue_date"
    inlines = [InvoiceItemInline, PaymentInline]


class RecurringItemInline(admin.TabularInline):
    model = RecurringItem
    extra = 1


@admin.register(RecurringInvoice)
class RecurringInvoiceAdmin(admin.ModelAdmin):
    list_display = ("client", "business", "frequency", "next_run", "active")
    list_filter = ("business", "frequency", "active")
    list_editable = ("next_run", "active")
    inlines = [RecurringItemInline]
