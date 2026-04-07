from django.urls import path
from django.views.generic import RedirectView

from .views import (
    checkout_cancel_view,
    checkout_status_view,
    checkout_success_view,
    credit_checkout_view,
    dashboard_view,
    login_view,
    logout_view,
    subscription_checkout_view,
    webhook_view,
)

urlpatterns = [
    path("", RedirectView.as_view(url="/login/"), name="root"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("checkout/subscription/", subscription_checkout_view, name="subscription_checkout"),
    path("checkout/credit/", credit_checkout_view, name="credit_checkout"),
    path("checkout/success/", checkout_success_view, name="checkout_success"),
    path("checkout/cancel/", checkout_cancel_view, name="checkout_cancel"),
    path("api/checkout-status/", checkout_status_view, name="checkout_status"),
    path("webhook/", webhook_view, name="webhook"),
]
