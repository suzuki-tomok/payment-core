"""Webhook handler tests.

各 handler は DB 操作のみ. event/details DTO を組み立てて handler を呼び、
DB の状態を assert するだけのシンプル構造.
"""

import pytest

from payment.models import Payment
from payment.services.webhook_handlers import (
    handle_charge_refunded,
    handle_checkout_completed,
    handle_checkout_expired,
)
from payment.stripe import (
    ConstructWebhookEventOutput,
    GetCompletedSessionDetailsOutput,
)
from payment.tests.factories import PaymentFactory


def _completed_event(session_id: str) -> ConstructWebhookEventOutput:
    return ConstructWebhookEventOutput(
        event_id="evt_test_1",
        event_type="checkout.session.completed",
        data={"id": session_id},
    )


def _expired_event(session_id: str) -> ConstructWebhookEventOutput:
    return ConstructWebhookEventOutput(
        event_id="evt_test_2",
        event_type="checkout.session.expired",
        data={"id": session_id},
    )


def _refunded_event(payment_intent_id: str) -> ConstructWebhookEventOutput:
    return ConstructWebhookEventOutput(
        event_id="evt_test_3",
        event_type="charge.refunded",
        data={"payment_intent": payment_intent_id},
    )


# ============================================================================
# handle_checkout_completed
# ============================================================================

@pytest.mark.django_db
def test_completed_no_payment_noops():
    """Payment 不在 → エラーにならず何もしない (Stripe にリトライさせない)."""
    event = _completed_event("cs_unknown")
    details = GetCompletedSessionDetailsOutput(amount=500, description="X")

    handle_checkout_completed(event, details)

    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_completed_pending_to_succeeded():
    """PENDING/UNPAID → COMPLETED + SUCCEEDED + amount/description を Stripe 値で更新."""
    payment = PaymentFactory(
        stripe_session_id="cs_test_xyz",
        amount=999,  # 古い値 (Stripe 確定前)
        description="old",
        session_status=Payment.SessionStatus.PENDING,
        payment_status=Payment.PaymentStatus.UNPAID,
    )
    event = _completed_event("cs_test_xyz")
    details = GetCompletedSessionDetailsOutput(amount=2000, description="confirmed")

    handle_checkout_completed(event, details)

    payment.refresh_from_db()
    assert payment.session_status == Payment.SessionStatus.COMPLETED
    assert payment.payment_status == Payment.PaymentStatus.SUCCEEDED
    assert payment.amount == 2000
    assert payment.description == "confirmed"


@pytest.mark.django_db
def test_completed_already_succeeded_noops():
    """既 SUCCEEDED → 上書きしない (冪等性 — webhook 二重送信対策)."""
    payment = PaymentFactory(
        stripe_session_id="cs_test_xyz",
        amount=2000,
        description="confirmed",
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.SUCCEEDED,
    )
    event = _completed_event("cs_test_xyz")
    # 全く違う値を渡しても上書きされないこと
    details = GetCompletedSessionDetailsOutput(amount=9999, description="should not overwrite")

    handle_checkout_completed(event, details)

    payment.refresh_from_db()
    assert payment.amount == 2000
    assert payment.description == "confirmed"
    assert payment.payment_status == Payment.PaymentStatus.SUCCEEDED


@pytest.mark.django_db
def test_completed_already_refunded_not_overwritten():
    """既 REFUNDED → SUCCEEDED で上書きしない (REFUNDED が新しい真実)."""
    payment = PaymentFactory(
        stripe_session_id="cs_test_xyz",
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.REFUNDED,
    )
    event = _completed_event("cs_test_xyz")
    details = GetCompletedSessionDetailsOutput(amount=1000, description="x")

    handle_checkout_completed(event, details)

    payment.refresh_from_db()
    assert payment.payment_status == Payment.PaymentStatus.REFUNDED  # まだ REFUNDED


# ============================================================================
# handle_checkout_expired
# ============================================================================

@pytest.mark.django_db
def test_expired_no_payment_noops():
    """Payment 不在 → エラーにならず何もしない."""
    event = _expired_event("cs_unknown")
    handle_checkout_expired(event)
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_expired_marks_session_expired_only():
    """session_status のみ EXPIRED に更新、payment_status は不変."""
    payment = PaymentFactory(
        stripe_session_id="cs_test_xyz",
        session_status=Payment.SessionStatus.PENDING,
        payment_status=Payment.PaymentStatus.UNPAID,
    )
    event = _expired_event("cs_test_xyz")

    handle_checkout_expired(event)

    payment.refresh_from_db()
    assert payment.session_status == Payment.SessionStatus.EXPIRED
    assert payment.payment_status == Payment.PaymentStatus.UNPAID  # 不変


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
def test_refunded_marks_payment_refunded_only():
    """payment_status のみ REFUNDED、session_status は不変."""
    payment = PaymentFactory(
        stripe_payment_id="pi_test_xyz",
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.SUCCEEDED,
    )
    event = _refunded_event("pi_test_xyz")

    handle_charge_refunded(event)

    payment.refresh_from_db()
    assert payment.payment_status == Payment.PaymentStatus.REFUNDED
    assert payment.session_status == Payment.SessionStatus.COMPLETED  # 不変
