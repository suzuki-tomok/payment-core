"""stripe_webhook_view (POST /payment/webhook/) の HTTP テスト.

view の責務:
    1. 署名検証 (失敗 → 400)
    2. 冪等性チェック (EventLog 既存 → 200, handler 呼ばない)
    3. event_type ごとに dispatch
    4. 各 event の atomic: handler + EventLog 同 tx

handler 挙動:
    - checkout.session.completed: Payment 新規作成
    - checkout.session.expired: no-op
    - charge.refunded: is_refunded=True
"""

import pytest

from payment.models import Payment, StripeWebhookEventLog
from payment.stripe import (
    ConstructWebhookEventOutput,
    GetCompletedSessionDetailsOutput,
    PaymentConfigError,
    PaymentSystemError,
    WebhookSignatureError,
)
from payment.tests.factories import (
    PaymentFactory,
    StripeCustomerFactory,
    StripeWebhookEventLogFactory,
)


def _post_webhook(client):
    """共通 POST 呼び出し. payload は mock してるので任意."""
    return client.post(
        "/payment/webhook/",
        data=b"any-payload",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="test-signature",
    )


# ============================================================================
# 署名検証 / 冪等性 / 想定外 type
# ============================================================================

def test_invalid_signature_returns_400(client, mock_stripe_client):
    mock_stripe_client.construct_webhook_event.side_effect = WebhookSignatureError("bad sig")

    response = _post_webhook(client)

    assert response.status_code == 400


@pytest.mark.django_db
def test_idempotent_already_processed_returns_200(client, mock_stripe_client):
    """既処理 event_id (EventLog 存在) → 200, handler 呼ばれない."""
    StripeWebhookEventLogFactory(event_id="evt_dup")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_dup", event_type="checkout.session.completed",
        data={"id": "cs_x", "customer": "cus_x", "metadata": {"order_id": "o-1"}},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    mock_stripe_client.get_completed_session_details.assert_not_called()


@pytest.mark.django_db
def test_unhandled_event_type_returns_200_no_eventlog(client, mock_stripe_client):
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_unknown", event_type="customer.created",
        data={"id": "cus_x"},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_unknown").exists()


# ============================================================================
# checkout.session.completed (Payment 新規作成)
# ============================================================================

@pytest.mark.django_db
def test_completed_creates_payment(client, mock_stripe_client):
    """checkout.session.completed → Payment 新規作成 + EventLog 記録 + 200."""
    StripeCustomerFactory(stripe_customer_id="cus_test_x")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_1", event_type="checkout.session.completed",
        data={
            "id": "cs_x",
            "customer": "cus_test_x",
            "metadata": {"order_id": "order-1"},
        },
    )
    mock_stripe_client.get_completed_session_details.return_value = (
        GetCompletedSessionDetailsOutput(
            amount=2000, description="confirmed", payment_intent_id="pi_confirmed",
        )
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    payment = Payment.objects.get(order_id="order-1")
    assert payment.stripe_session_id == "cs_x"
    assert payment.stripe_payment_id == "pi_confirmed"
    assert payment.amount == 2000
    assert payment.is_refunded is False
    assert StripeWebhookEventLog.objects.filter(event_id="evt_1").exists()


@pytest.mark.django_db
def test_completed_retrieve_transient_returns_502(client, mock_stripe_client):
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_2", event_type="checkout.session.completed",
        data={"id": "cs_x", "customer": "cus_x", "metadata": {"order_id": "o-1"}},
    )
    mock_stripe_client.get_completed_session_details.side_effect = PaymentSystemError("transient")

    response = _post_webhook(client)

    assert response.status_code == 502
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_2").exists()


@pytest.mark.django_db
def test_completed_retrieve_permanent_returns_500(client, mock_stripe_client):
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_3", event_type="checkout.session.completed",
        data={"id": "cs_x", "customer": "cus_x", "metadata": {"order_id": "o-1"}},
    )
    mock_stripe_client.get_completed_session_details.side_effect = PaymentConfigError("perm")

    response = _post_webhook(client)

    assert response.status_code == 500


@pytest.mark.django_db
def test_completed_handler_failure_returns_500(
    client, mock_stripe_client, monkeypatch,
):
    """handler が例外 → 500. EventLog も rollback."""
    StripeCustomerFactory(stripe_customer_id="cus_test_x")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_4", event_type="checkout.session.completed",
        data={"id": "cs_x", "customer": "cus_test_x", "metadata": {"order_id": "order-1"}},
    )
    mock_stripe_client.get_completed_session_details.return_value = (
        GetCompletedSessionDetailsOutput(amount=1000, description="x", payment_intent_id="pi_x")
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr("payment.views.handle_checkout_completed", boom)

    response = _post_webhook(client)

    assert response.status_code == 500
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_4").exists()


@pytest.mark.django_db
def test_completed_metadata_missing_returns_500(client, mock_stripe_client):
    """metadata.order_id 不在 → handler が WebhookContractError raise → view 500 + EventLog 無し."""
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_no_metadata", event_type="checkout.session.completed",
        data={"id": "cs_x", "customer": "cus_x", "metadata": {}},
    )
    mock_stripe_client.get_completed_session_details.return_value = (
        GetCompletedSessionDetailsOutput(amount=1000, description="x", payment_intent_id="pi_x")
    )

    response = _post_webhook(client)

    assert response.status_code == 500
    # EventLog は書かれない (Stripe にリトライさせる + 我々で原因調査)
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_no_metadata").exists()


# ============================================================================
# checkout.session.expired (no-op)
# ============================================================================

@pytest.mark.django_db
def test_expired_returns_200_no_db_change(client, mock_stripe_client):
    """expired は no-op だが EventLog は記録 + 200 を返す."""
    StripeCustomerFactory()
    PaymentFactory(order_id="order-1", stripe_session_id="cs_x")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_exp", event_type="checkout.session.expired",
        data={"id": "cs_x", "metadata": {"order_id": "order-1"}},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    assert StripeWebhookEventLog.objects.filter(event_id="evt_exp").exists()
    # Payment は変化なし
    assert Payment.objects.count() == 1


# ============================================================================
# charge.refunded
# ============================================================================

@pytest.mark.django_db
def test_refunded_marks_is_refunded(client, mock_stripe_client):
    """charge.refunded → is_refunded=True + EventLog + 200."""
    payment = PaymentFactory(stripe_payment_id="pi_x", is_refunded=False)
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_ref", event_type="charge.refunded",
        data={"payment_intent": "pi_x"},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.is_refunded is True
    assert payment.refunded_at is not None
    assert StripeWebhookEventLog.objects.filter(event_id="evt_ref").exists()
