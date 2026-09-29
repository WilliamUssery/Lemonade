from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("<uuid:token>/", views.pay, name="pay"),
    path("<uuid:token>/start/", views.start_payment, name="start"),
    path("<uuid:token>/done/", views.done, name="done"),
]
