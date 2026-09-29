from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.payment_list, name="list"),
    path("<int:pk>/confirm/", views.payment_confirm, name="confirm"),
    path("<int:pk>/reject/", views.payment_reject, name="reject"),
    path("square/webhook/", views.square_webhook, name="square_webhook"),
    path("simulate/<int:pk>/", views.simulate_checkout, name="simulate"),
]
