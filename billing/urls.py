from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_create, name="create"),
    path("export.csv", views.invoice_export, name="export"),
    path("<int:pk>/", views.invoice_detail, name="detail"),
    path("<int:pk>/edit/", views.invoice_edit, name="edit"),
    path("<int:pk>/send/", views.invoice_send, name="send"),
    path("<int:pk>/void/", views.invoice_void, name="void"),
]
