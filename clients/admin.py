from django.contrib import admin

from .models import Client, ClientBusiness


class ClientBusinessInline(admin.TabularInline):
    model = ClientBusiness
    extra = 1


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone", "business_list", "created_at")
    list_filter = ("businesses",)
    search_fields = ("first_name", "last_name", "email", "phone")
    inlines = [ClientBusinessInline]

    @admin.display(description="Businesses")
    def business_list(self, obj):
        return ", ".join(b.name for b in obj.businesses.all())
