"""Webhook handler tests.

handler 一覧:
    - handle_checkout_completed: Payment を新規作成 (1 order = 1 successful Payment)
    - handle_checkout_expired: 何もしない (no-op)
    - handle_charge_refunded: 既存 Payment の is_refunded=True に
"""

import pytest

from payment.models import Payment
from payment.services.exceptions import WebhookContractError
from payment.services.webhook_handlers import (
    handle_charge_refunded,
    handle_checkout_completed,
    handle_checkout_expired,
)
from payment.stripe import (
    ConstructWebhookEventOutput,
    GetCompletedSessionDetailsOutput,
)
from payment.tests.factories import PaymentFactory, StripeCustomerFactory


def _completed_event(
    session_id: str = "cs_test_x",
    customer_id: str = "cus_test_x",
    order_id: str = "order-1",
    event_id: str = "evt_test_1",
) -> ConstructWebhookEventOutput:
    return ConstructWebhookEventOutput(
        event_id=event_id,
        event_type="checkout.session.completed",
        data={
            "id": session_id,
            "customer": customer_id,
            "metadata": {"order_id": order_id},
        },
    )


def _expired_event(session_id: str = "cs_test_x") -> ConstructWebhookEventOutput:
    return ConstructWebhookEventOutput(
        event_id="evt_test_2",
        event_type="checkout.session.expired",
        data={"id": session_id, "metadata": {"order_id": "order-1"}},
    )


def _refunded_event(payment_intent_id: str) -> ConstructWebhookEventOutput:
    return ConstructWebhookEventOutput(
        event_id="evt_test_3",
        event_type="charge.refunded",
        data={"payment_intent": payment_intent_id},
    )


# ============================================================================
# handle_checkout_completed (Payment を新規作成)
# ============================================================================

@pytest.mark.django_db
def test_completed_creates_new_payment():
    """初回受信: Payment を新規作成. amount/description/payment_intent_id を Stripe 値で."""
    customer = StripeCustomerFactory(stripe_customer_id="cus_test_x")
    event = _completed_event(
        session_id="cs_test_xyz",
        customer_id="cus_test_x",
        order_id="order-42",
    )
    details = GetCompletedSessionDetailsOutput(
        amount=5000, description="confirmed", payment_intent_id="pi_confirmed",
    )

    handle_checkout_completed(event, details)

    payment = Payment.objects.get(order_id="order-42")
    assert payment.stripe_customer == customer
    assert payment.stripe_session_id == "cs_test_xyz"
    assert payment.stripe_payment_id == "pi_confirmed"
    assert payment.amount == 5000
    assert payment.description == "confirmed"
    assert payment.is_refunded is False


@pytest.mark.django_db
def test_completed_existing_payment_skipped():
    """既に同 order_id の Payment 存在 → 何もしない (冪等性 — webhook 二重送信 / 重複決済対策)."""
    customer = StripeCustomerFactory(stripe_customer_id="cus_test_x")
    PaymentFactory(
        order_id="order-42",
        stripe_session_id="cs_first",
        stripe_payment_id="pi_first",
        amount=5000,
        description="first",
        stripe_customer=customer,
    )

    # 別 session の同 order_id event が来たら無視
    event = _completed_event(
        session_id="cs_second",  # ← 別 session
        customer_id="cus_test_x",
        order_id="order-42",
    )
    details = GetCompletedSessionDetailsOutput(
        amount=9999, description="should not overwrite", payment_intent_id="pi_second",
    )

    handle_checkout_completed(event, details)

    # 既存値のまま
    assert Payment.objects.count() == 1
    payment = Payment.objects.get(order_id="order-42")
    assert payment.amount == 5000
    assert payment.stripe_session_id == "cs_first"
    assert payment.stripe_payment_id == "pi_first"


@pytest.mark.django_db
def test_completed_missing_metadata_order_id_raises():
    """metadata に order_id 無し → WebhookContractError raise (view が 500 にする)."""
    StripeCustomerFactory(stripe_customer_id="cus_test_x")
    event = ConstructWebhookEventOutput(
        event_id="evt_x",
        event_type="checkout.session.completed",
        data={"id": "cs_x", "customer": "cus_test_x", "metadata": {}},
    )
    details = GetCompletedSessionDetailsOutput(
        amount=5000, description="x", payment_intent_id="pi_x",
    )

    with pytest.raises(WebhookContractError):
        handle_checkout_completed(event, details)

    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_completed_missing_customer_raises():
    """data.customer 無し → WebhookContractError raise."""
    event = ConstructWebhookEventOutput(
        event_id="evt_x",
        event_type="checkout.session.completed",
        data={"id": "cs_x", "metadata": {"order_id": "order-1"}},
    )
    details = GetCompletedSessionDetailsOutput(
        amount=5000, description="x", payment_intent_id="pi_x",
    )

    with pytest.raises(WebhookContractError):
        handle_checkout_completed(event, details)

    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_completed_unknown_customer_raises():
    """指定 customer_id が DB に存在しない → WebhookContractError raise."""
    event = _completed_event(customer_id="cus_unknown")
    details = GetCompletedSessionDetailsOutput(
        amount=5000, description="x", payment_intent_id="pi_x",
    )

    with pytest.raises(WebhookContractError):
        handle_checkout_completed(event, details)

    assert Payment.objects.count() == 0


# ============================================================================
# handle_checkout_expired (no-op)
# ============================================================================

@pytest.mark.django_db
def test_expired_does_nothing():
    """expired は DB 操作なし (log のみ)."""
    StripeCustomerFactory(stripe_customer_id="cus_test_x")
    PaymentFactory(order_id="order-1", stripe_session_id="cs_test_x")

    handle_checkout_expired(_expired_event(session_id="cs_test_x"))

    # Payment 数は変わらない
    assert Payment.objects.count() == 1
    payment = Payment.objects.get(order_id="order-1")
    # フィールド変化なし
    assert payment.is_refunded is False


# ============================================================================
# handle_charge_refunded
# ============================================================================

@pytest.mark.django_db
def test_refunded_no_payment_noops():
    """payment_intent_id で検索して不在 → 何もしない."""
    event = _refunded_event("pi_unknown")
    handle_charge_refunded(event)
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_refunded_marks_payment_refunded():
    """既存 Payment.is_refunded を True + refunded_at セット."""
    payment = PaymentFactory(stripe_payment_id="pi_test_xyz", is_refunded=False)
    event = _refunded_event("pi_test_xyz")

    handle_charge_refunded(event)

    payment.refresh_from_db()
    assert payment.is_refunded is True
    assert payment.refunded_at is not None
