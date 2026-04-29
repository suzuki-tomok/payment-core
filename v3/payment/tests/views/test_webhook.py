"""stripe_webhook_view (POST /payment/webhook/) の HTTP テスト.

view の責務:
    1. 署名検証 (失敗 → 400)
    2. 冪等性チェック (EventLog 既存 → 200, handler 呼ばない)
    3. event_type ごとに dispatch
    4. 各 event の atomic: handler + EventLog 同 tx

Stripe SDK は client.construct_webhook_event を mock することで全て差替.
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
from payment.tests.factories import PaymentFactory, StripeWebhookEventLogFactory


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
    """署名検証失敗 → 400 (Stripe にリトライさせない)."""
    mock_stripe_client.construct_webhook_event.side_effect = WebhookSignatureError("bad sig")

    response = _post_webhook(client)

    assert response.status_code == 400


@pytest.mark.django_db
def test_idempotent_already_processed_returns_200(client, mock_stripe_client):
    """既処理 event_id (EventLog 存在) → 200, handler 呼ばれない."""
    StripeWebhookEventLogFactory(event_id="evt_dup")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_dup", event_type="checkout.session.completed",
        data={"id": "cs_x"},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    # 事前 fetch も handler 呼出も発生しない
    mock_stripe_client.get_completed_session_details.assert_not_called()


@pytest.mark.django_db
def test_unhandled_event_type_returns_200_no_eventlog(client, mock_stripe_client):
    """想定外 event_type → 200 (Stripe にリトライさせない) かつ EventLog は記録しない."""
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_unknown", event_type="customer.created",
        data={"id": "cus_x"},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_unknown").exists()


# ============================================================================
# checkout.session.completed
# ============================================================================

@pytest.mark.django_db
def test_completed_processes_handler(client, mock_stripe_client):
    """checkout.session.completed → Payment 更新 + EventLog 記録 + 200."""
    payment = PaymentFactory(stripe_session_id="cs_x")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_1", event_type="checkout.session.completed",
        data={"id": "cs_x"},
    )
    mock_stripe_client.get_completed_session_details.return_value = (
        GetCompletedSessionDetailsOutput(amount=2000, description="confirmed")
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.payment_status == Payment.PaymentStatus.SUCCEEDED
    assert payment.session_status == Payment.SessionStatus.COMPLETED
    assert payment.amount == 2000
    assert StripeWebhookEventLog.objects.filter(event_id="evt_1").exists()


@pytest.mark.django_db
def test_completed_retrieve_transient_returns_502(client, mock_stripe_client):
    """事前 fetch (get_completed_session_details) で PaymentSystemError → 502 (Stripe にリトライ)."""
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_2", event_type="checkout.session.completed",
        data={"id": "cs_x"},
    )
    mock_stripe_client.get_completed_session_details.side_effect = PaymentSystemError("transient")

    response = _post_webhook(client)

    assert response.status_code == 502
    # EventLog は記録されない (Stripe 再送で再処理させる)
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_2").exists()


@pytest.mark.django_db
def test_completed_retrieve_permanent_returns_500(client, mock_stripe_client):
    """事前 fetch で PaymentConfigError → 500."""
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_3", event_type="checkout.session.completed",
        data={"id": "cs_x"},
    )
    mock_stripe_client.get_completed_session_details.side_effect = PaymentConfigError("perm")

    response = _post_webhook(client)

    assert response.status_code == 500


@pytest.mark.django_db
def test_completed_handler_failure_returns_500(
    client, mock_stripe_client, monkeypatch,
):
    """atomic 内の handler が例外 → 500. EventLog も記録されない."""
    PaymentFactory(stripe_session_id="cs_x")
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_4", event_type="checkout.session.completed",
        data={"id": "cs_x"},
    )
    mock_stripe_client.get_completed_session_details.return_value = (
        GetCompletedSessionDetailsOutput(amount=1000, description="x")
    )

    # views.py が import している handle_checkout_completed を差替
    def boom(*_args, **_kwargs):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr("payment.views.handle_checkout_completed", boom)

    response = _post_webhook(client)

    assert response.status_code == 500
    # atomic rollback により EventLog も記録されない
    assert not StripeWebhookEventLog.objects.filter(event_id="evt_4").exists()


# ============================================================================
# checkout.session.expired
# ============================================================================

@pytest.mark.django_db
def test_expired_processes_handler(client, mock_stripe_client):
    """checkout.session.expired → session_status=EXPIRED + EventLog + 200."""
    payment = PaymentFactory(
        stripe_session_id="cs_x",
        session_status=Payment.SessionStatus.PENDING,
    )
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_exp", event_type="checkout.session.expired",
        data={"id": "cs_x"},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.session_status == Payment.SessionStatus.EXPIRED
    assert StripeWebhookEventLog.objects.filter(event_id="evt_exp").exists()


# ============================================================================
# charge.refunded
# ============================================================================

@pytest.mark.django_db
def test_refunded_processes_handler(client, mock_stripe_client):
    """charge.refunded → payment_status=REFUNDED + EventLog + 200."""
    payment = PaymentFactory(
        stripe_payment_id="pi_x",
        payment_status=Payment.PaymentStatus.SUCCEEDED,
    )
    mock_stripe_client.construct_webhook_event.return_value = ConstructWebhookEventOutput(
        event_id="evt_ref", event_type="charge.refunded",
        data={"payment_intent": "pi_x"},
    )

    response = _post_webhook(client)

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.payment_status == Payment.PaymentStatus.REFUNDED
    assert StripeWebhookEventLog.objects.filter(event_id="evt_ref").exists()
