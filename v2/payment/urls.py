from django.urls import path

from payment.views.stripe_checkout import cancel_view, status_view, success_view
from payment.views.stripe_webhook import webhook_view

app_name = "payment"

urlpatterns = [
    path("checkout/success/", success_view, name="checkout_success"),
    path("checkout/cancel/", cancel_view, name="checkout_cancel"),
    path("status/", status_view, name="status"),
    path("webhook/", webhook_view, name="webhook"),
]
