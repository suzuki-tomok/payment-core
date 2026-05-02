"""Stripe webhook event 別の handler 関数.

設計:
    - 各 handler は DB 更新だけを行う (外部 API は呼ばない).
    - 必要な事前 fetch は view 側で済ませて DTO で渡す.
    - atomic / EventLog 書き込みは view 側で集約 (handler は知らない).
    - Payment は handle_checkout_completed で **新規作成** する (起票時に作らない).

handler 一覧:
    - handle_checkout_completed: Payment を新規作成 (1 order = 1 successful Payment, 冪等)
    - handle_checkout_expired: 何もしない (Stripe 側の概念で DB に記録不要)
    - handle_charge_refunded: 既存 Payment を返金済 (is_refunded=True) に更新
"""

import logging

from django.utils import timezone

from payment.models import Payment, StripeCustomer
from payment.stripe.dtos import (
    ConstructWebhookEventOutput,
    GetCompletedSessionDetailsOutput,
)

from .exceptions import WebhookContractError

logger = logging.getLogger(__name__)


def handle_checkout_completed(
    event: ConstructWebhookEventOutput,
    details: GetCompletedSessionDetailsOutput,
) -> None:
    """checkout.session.completed: Payment を新規作成.

    起票時には Payment が無いので、ここで初めて作成する.
    既に同 order_id の Payment が存在する場合 (= webhook 再送 or 古い URL での重複決済) は
    何もしない (冪等).

    event.data.metadata.order_id で逆引きするため、Session.create 時に metadata に
    order_id をセットしておくこと (services.checkout 側の責務).

    Raises:
        WebhookContractError: metadata.order_id / customer 不在、StripeCustomer 不在等.
            「我々が起票してない event」or「起票時にバグった」のいずれか. スルーすると
            潜在バグを見逃すため明示的に raise → view が 500 を返し Stripe にリトライさせる.
    """
    metadata = event.data.get("metadata") or {}
    order_id = metadata.get("order_id")
    if not order_id:
        # 我々が起票した Session には必ず metadata.order_id が入っている (services.checkout の責務).
        # 不在 = 外部由来 Session or 我々のバグ. スルーは怪しいので surface する.
        raise WebhookContractError(
            f"order_id missing from metadata (session_id={event.data.get('id')})",
        )

    stripe_session_id = event.data["id"]
    stripe_customer_id = event.data.get("customer")
    if not stripe_customer_id:
        raise WebhookContractError(
            f"customer missing from session (order_id={order_id}, session_id={stripe_session_id})",
        )

    # StripeCustomer は起票時に作成済のはず.
    customer = StripeCustomer.objects.filter(
        stripe_customer_id=stripe_customer_id,
    ).first()
    if customer is None:
        raise WebhookContractError(
            f"StripeCustomer not found (order_id={order_id}, "
            f"stripe_customer_id={stripe_customer_id})",
        )

    # 1 order = 1 successful Payment. 既存なら何もしない (冪等性).
    # webhook 再送、古い Session URL での重複決済どちらにも対応する.
    payment, created = Payment.objects.get_or_create(
        order_id=order_id,
        defaults={
            "stripe_customer": customer,
            "stripe_session_id": stripe_session_id,
            "stripe_payment_id": details.payment_intent_id,
            "amount": details.amount,
            "description": details.description,
        },
    )
    if not created:
        logger.warning(
            "Webhook: Payment already exists, skipping (likely duplicate session for same order)",
            extra={
                "order_id": order_id,
                "existing_session_id": payment.stripe_session_id,
                "duplicate_session_id": stripe_session_id,
            },
        )
        return

    logger.info(
        "Payment created",
        extra={
            "order_id": order_id,
            "session_id": stripe_session_id,
            "payment_intent_id": details.payment_intent_id,
            "amount": details.amount,
        },
    )


def handle_checkout_expired(event: ConstructWebhookEventOutput) -> None:
    """checkout.session.expired: 何もしない.

    Stripe Session が 24h で expire しても、本設計では DB に記録する状態を持たない.
    ユーザは「決済する」を再度押せば新しい Session が自動生成される.
    log のみ残す (運用観察用).
    """
    metadata = event.data.get("metadata") or {}
    logger.info(
        "Webhook: session expired (no DB action)",
        extra={
            "session_id": event.data.get("id"),
            "order_id": metadata.get("order_id"),
        },
    )


def handle_charge_refunded(event: ConstructWebhookEventOutput) -> None:
    """charge.refunded: Payment.is_refunded を True に更新.

    charge payload には session_id / metadata が含まれないため、payment_intent_id で
    Payment を引く. Payment.stripe_payment_id は handle_checkout_completed で確定済.
    """
    stripe_payment_id = event.data["payment_intent"]

    # is_refunded + refunded_at を更新. .update() は auto_now を発火しないため明示セット.
    updated = Payment.objects.filter(stripe_payment_id=stripe_payment_id).update(
        is_refunded=True,
        refunded_at=timezone.now(),
        updated_at=timezone.now(),
    )

    if updated == 0:
        logger.warning(
            "Payment not found for refund",
            extra={"stripe_payment_id": stripe_payment_id},
        )
    else:
        logger.info(
            "Payment refunded",
            extra={"stripe_payment_id": stripe_payment_id},
        )
