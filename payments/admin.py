from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "method", "amount", "fee", "status", "external_ref", "confirmed_by", "created_at")
    list_filter = ("status", "method", "invoice__business")
    search_fields = ("invoice__number", "external_ref")
    readonly_fields = ("created_at", "confirmed_at")
