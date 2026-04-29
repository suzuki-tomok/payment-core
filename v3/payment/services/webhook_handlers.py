"""Stripe webhook event 別の handler 関数.

設計:
    - 各 handler は DB 更新だけを行う (外部 API は呼ばない).
    - 必要な事前 fetch は view 側で済ませて DTO で渡す.
    - atomic / EventLog 書き込みは view 側で集約 (handler は知らない).
    - .update() は auto_now を発火しないため updated_at を明示的にセットする.
"""

import logging

from django.utils import timezone

from payment.models import Payment
from payment.stripe.dtos import (
    ConstructWebhookEventOutput,
    GetCompletedSessionDetailsOutput,
)

logger = logging.getLogger(__name__)


def handle_checkout_completed(
    event: ConstructWebhookEventOutput,
    details: GetCompletedSessionDetailsOutput,
) -> None:
    """checkout.session.completed: Payment を完了状態に更新.

    details は事前に view 側で StripeClient.get_completed_session_details() を呼んで
    取得した DTO を渡す (atomic 内で外部 API を呼ばないため).
    """
    stripe_session_id = event.data["id"]

    # Payment 取得 (status だけ select)
    payment = Payment.objects.filter(stripe_session_id=stripe_session_id).only(
        "id", "payment_status",
    ).first()
    if payment is None:
        # 我々が起票してない session
        logger.warning("Payment not found for stripe_session_id=%s", stripe_session_id)
        return

    # 既に確定 (SUCCEEDED / REFUNDED) なら上書きしない.
    # REFUNDED は完了後返金されたケースなので絶対に SUCCEEDED で上書きしてはいけない.
    if payment.payment_status in (
        Payment.PaymentStatus.SUCCEEDED,
        Payment.PaymentStatus.REFUNDED,
    ):
        logger.info(
            "Payment already finalized (status=%s) for stripe_session_id=%s",
            payment.payment_status, stripe_session_id,
        )
        return

    # 確定状態へ更新 (Stripe 側の真実値を amount / description / payment_intent_id に反映).
    # stripe_payment_id は ここで初めてセットされる (起票時は NULL — Stripe lazy PI のため).
    Payment.objects.filter(stripe_session_id=stripe_session_id).update(
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.SUCCEEDED,
        amount=details.amount,
        description=details.description,
        stripe_payment_id=details.payment_intent_id,
        updated_at=timezone.now(),
    )
    logger.info(
        "Payment completed: stripe_session_id=%s amount=%d",
        stripe_session_id, details.amount,
    )


def handle_checkout_expired(event: ConstructWebhookEventOutput) -> None:
    """checkout.session.expired: Payment.session_status を expired に更新."""
    stripe_session_id = event.data["id"]

    # session_status のみ更新 (payment_status は触らない)
    updated = Payment.objects.filter(stripe_session_id=stripe_session_id).update(
        session_status=Payment.SessionStatus.EXPIRED,
        updated_at=timezone.now(),
    )

    if updated == 0:
        logger.warning("Payment not found for stripe_session_id=%s", stripe_session_id)
    else:
        logger.info("Payment expired: stripe_session_id=%s", stripe_session_id)


def handle_charge_refunded(event: ConstructWebhookEventOutput) -> None:
    """charge.refunded: Payment.payment_status を refunded に更新.

    charge payload には session_id が含まれないため payment_intent_id で検索する.
    """
    stripe_payment_id = event.data["payment_intent"]

    # payment_status のみ更新 (session_status は触らない)
    updated = Payment.objects.filter(stripe_payment_id=stripe_payment_id).update(
        payment_status=Payment.PaymentStatus.REFUNDED,
        updated_at=timezone.now(),
    )

    if updated == 0:
        logger.warning("Payment not found for stripe_payment_id=%s", stripe_payment_id)
    else:
        logger.info("Payment refunded: stripe_payment_id=%s", stripe_payment_id)
