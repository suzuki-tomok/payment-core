"""mock_checkout_view (GET /payment/mock/checkout/<session_id>/) の HTTP テスト.

USE_MOCK_STRIPE=False で必ず 404. True 時のみ機能し、踏むと自動完了 → success_url リダイレクト.

mock 経路でも Payment は webhook handler 経由で新規作成される.
事前 PaymentFactory は不要 (StripeCustomer のみ事前必要).
"""

import pytest

from payment.models import Payment, StripeWebhookEventLog
from payment.tests.factories import StripeCustomerFactory


@pytest.mark.django_db
def test_returns_404_when_mock_disabled(client, settings):
    """USE_MOCK_STRIPE=False → 404 (本番事故防止)."""
    settings.USE_MOCK_STRIPE = False

    response = client.get("/payment/mock/checkout/cs_x/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_returns_404_when_session_unknown(client, settings, real_mock_client):
    """USE_MOCK_STRIPE=True だが mock client の _sessions に session が無い → 404."""
    settings.USE_MOCK_STRIPE = True

    response = client.get("/payment/mock/checkout/cs_unknown/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_redirects_to_success_url_and_creates_payment(client, settings, real_mock_client):
    """mock session 存在 → handler 発火 → Payment 新規作成 → success_url リダイレクト."""
    settings.USE_MOCK_STRIPE = True

    # 事前: StripeCustomer (起票時に作成される想定. mock_checkout_view が逆引きする)
    StripeCustomerFactory(stripe_customer_id="cus_mock_xxx")

    # mock session 情報をセットアップ (本物 Session.create で記録される情報を擬似的に注入)
    real_mock_client._sessions["cs_mock_x"] = {
        "amount": 1000,
        "description": "Product",
        "success_url": "https://example.com/success?order_id=foo",
        "cancel_url": "https://example.com/cancel?order_id=foo",
        "payment_intent_id": "pi_mock_x",
        "metadata": {"order_id": "order-mock-1"},
        "customer_id": "cus_mock_xxx",
    }

    response = client.get("/payment/mock/checkout/cs_mock_x/")

    assert response.status_code == 302
    assert response.url == "https://example.com/success?order_id=foo"

    # Payment が新規作成された
    payment = Payment.objects.get(order_id="order-mock-1")
    assert payment.stripe_session_id == "cs_mock_x"
    assert payment.stripe_payment_id == "pi_mock_x"
    assert payment.amount == 1000
    assert payment.is_refunded is False

    # EventLog 記録
    assert StripeWebhookEventLog.objects.filter(
        event_type="checkout.session.completed",
    ).exists()
