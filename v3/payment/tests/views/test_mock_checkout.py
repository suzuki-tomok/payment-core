"""mock_checkout_view (GET /payment/mock/checkout/<session_id>/) の HTTP テスト.

USE_MOCK_STRIPE=False で必ず 404. True 時のみ機能し、踏むと自動完了 → success_url リダイレクト.
"""

import pytest

from payment.models import Payment, StripeWebhookEventLog
from payment.tests.factories import PaymentFactory


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
    # _sessions は空のまま

    response = client.get("/payment/mock/checkout/cs_unknown/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_redirects_to_success_url_and_marks_succeeded(client, settings, real_mock_client):
    """mock session 存在 → handler 発火 → Payment SUCCEEDED → success_url にリダイレクト."""
    settings.USE_MOCK_STRIPE = True

    # Payment + mock session 情報をセットアップ
    payment = PaymentFactory(
        stripe_session_id="cs_mock_x",
        amount=1000,
        description="Product",
        session_status=Payment.SessionStatus.PENDING,
        payment_status=Payment.PaymentStatus.UNPAID,
    )
    real_mock_client._sessions["cs_mock_x"] = {
        "amount": 1000,
        "description": "Product",
        "success_url": "https://example.com/success?order_id=foo",
        "cancel_url": "https://example.com/cancel?order_id=foo",
        "payment_intent_id": "pi_x",
    }

    response = client.get("/payment/mock/checkout/cs_mock_x/")

    # success_url にリダイレクト
    assert response.status_code == 302
    assert response.url == "https://example.com/success?order_id=foo"

    # Payment が SUCCEEDED になってる
    payment.refresh_from_db()
    assert payment.payment_status == Payment.PaymentStatus.SUCCEEDED
    assert payment.session_status == Payment.SessionStatus.COMPLETED

    # EventLog が記録されてる (event_id は evt_mock_<uuid> なので存在判定で十分)
    assert StripeWebhookEventLog.objects.filter(
        event_type="checkout.session.completed",
    ).exists()
