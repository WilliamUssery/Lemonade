from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "DualLedger Admin"
admin.site.site_title = "DualLedger Admin"
admin.site.index_title = "Manage businesses, clients, invoices and payments"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("dashboard.urls")),
    path("clients/", include("clients.urls")),
    path("invoices/", include("billing.urls")),
    path("payments/", include("payments.urls")),
    path("pay/", include("portal.urls")),
]
