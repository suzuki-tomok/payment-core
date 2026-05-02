from django.urls import path

from demo.views import checkout_view, index_view, status_view

app_name = "demo"

urlpatterns = [
    path("", index_view, name="index"),
    path("checkout/", checkout_view, name="checkout"),
    path("status/", status_view, name="status"),
]
