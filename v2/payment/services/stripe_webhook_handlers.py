"""Stripe webhook イベントごとのハンドラ. 内部用 (payment app の view からのみ呼ぶ)."""

import logging
from typing import Any

from payment.models import Payment

# Stripe SDK の動的オブジェクト (LineItem 等) は厳密な型が公開されてないので Any.

logger = logging.getLogger(__name__)


class StripeWebhookHandlers:
    """Stripe webhook の event_type ごとのハンドラ集約.

    各メソッドは DB 操作のみを行い、外部 API 呼び出しは含まない.
    呼び出し側 (view) で必要な事前データを取得した上で、atomic で wrap して呼ぶ前提.
    """

    @staticmethod
    def handle_checkout_completed(data: dict[str, Any], line_item: Any) -> None:  # noqa: ANN401
        """checkout.session.completed: Payment を完了に更新.

        line_item は事前に view 側で stripe.Session.retrieve(expand=["line_items"]) して
        取得した line_items.data[0] を渡す (atomic 内で外部 API を呼ばないため).
        """
        stripe_session_id = data["id"]

        # 1. Payment 取得 (status だけ select)
        payment = Payment.objects.filter(stripe_session_id=stripe_session_id).only(
            "id", "payment_status",
        ).first()

        # 2. 未発見なら no-op (我々が起票してない session)
        if payment is None:
            logger.warning("Payment not found for stripe_session_id=%s", stripe_session_id)
            return

        # 3. 既に確定状態 (succeeded / refunded) なら no-op
        # SUCCEEDED は既処理. REFUNDED は完了後に返金されたので上書きしない.
        if payment.payment_status in (
            Payment.PaymentStatus.SUCCEEDED,
            Payment.PaymentStatus.REFUNDED,
        ):
            logger.info(
                "Payment already finalized (status=%s) for stripe_session_id=%s",
                payment.payment_status, stripe_session_id,
            )
            return

        # 4. line_item から確定額 / 説明を取得 (Stripe 側の真実値)
        amount = line_item.amount_total
        description = line_item.description or ""

        # 5. Payment を完了状態に更新 (session/payment 両方)
        Payment.objects.filter(stripe_session_id=stripe_session_id).update(
            session_status=Payment.SessionStatus.COMPLETED,
            payment_status=Payment.PaymentStatus.SUCCEEDED,
            amount=amount,
            description=description,
        )
        logger.info("Payment completed: stripe_session_id=%s amount=%d", stripe_session_id, amount)

    @staticmethod
    def handle_checkout_expired(data: dict[str, Any]) -> None:
        """checkout.session.expired: Payment.session_status を expired に更新."""
        stripe_session_id = data["id"]

        # 1. session_status のみ更新 (payment_status は触らない)
        updated = Payment.objects.filter(stripe_session_id=stripe_session_id).update(
            session_status=Payment.SessionStatus.EXPIRED,
        )

        # 2. 結果ログ (0件なら未発見の警告)
        if updated == 0:
            logger.warning("Payment not found for stripe_session_id=%s", stripe_session_id)
        else:
            logger.info("Payment expired: stripe_session_id=%s", stripe_session_id)

    @staticmethod
    def handle_charge_refunded(data: dict[str, Any]) -> None:
        """charge.refunded: Payment.payment_status を refunded に更新.

        payload には session_id が含まれないため payment_intent_id で検索する.
        """
        # 1. payment_intent_id で検索 (charge payload には session_id 無し)
        stripe_payment_id = data["payment_intent"]

        # 2. payment_status のみ更新 (session_status は触らない)
        updated = Payment.objects.filter(stripe_payment_id=stripe_payment_id).update(
            payment_status=Payment.PaymentStatus.REFUNDED,
        )

        # 3. 結果ログ (0件なら未発見の警告)
        if updated == 0:
            logger.warning("Payment not found for stripe_payment_id=%s", stripe_payment_id)
        else:
            logger.info("Payment refunded: stripe_payment_id=%s", stripe_payment_id)
