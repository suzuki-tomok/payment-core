"""payment app の URL routing.

config/urls.py で /payment/ にマウントされる前提.
"""

from django.urls import path

from payment.views import (
    cancel_view,
    create_checkout_view,
    mock_checkout_view,
    stripe_webhook_view,
    success_view,
)

app_name = "payment"

# status_view (polling 用) は廃止. 決済結果は webhook で DB 反映され、
# caller (consumer) は payment.services.checkout.get_payment_status() で照会する.
urlpatterns = [
    path("checkout/", create_checkout_view, name="checkout"),
    path("checkout/success/", success_view, name="checkout_success"),
    path("checkout/cancel/", cancel_view, name="checkout_cancel"),
    path("webhook/", stripe_webhook_view, name="webhook"),
    # USE_MOCK_STRIPE=True の時のみ機能する dev 用. False なら view が 404 を返す.
    path("mock/checkout/<str:session_id>/", mock_checkout_view, name="mock_checkout"),
]
