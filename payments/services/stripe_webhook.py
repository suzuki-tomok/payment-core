import logging
from datetime import UTC, datetime

import stripe
from django.conf import settings

from ..models import (
    CheckoutSession,
    CreditHistory,
    CreditPlan,
    InvoiceHistory,
    StripeCustomer,
    SubscriptionHistory,
    SubscriptionPlan,
)

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeWebhookService:
    """Stripe Webhook のハンドラ."""

    # ========================================
    # 署名検証
    # ========================================

    @staticmethod
    def verify_webhook(payload: bytes, sig_header: str) -> dict:  # type: ignore[type-arg]
        """Webhook の署名を検証してイベントを返す.

        Stripe が送ってきた payload と署名ヘッダーを
        WEBHOOK_SECRET で検証し、改ざんされていないことを確認する。
        """
        return stripe.Webhook.construct_event(  # type: ignore[return-value]
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )

    # ========================================
    # checkout.session.completed
    # ========================================

    @staticmethod
    def handle_checkout_completed(data: object) -> None:
        """Checkout 完了時: CheckoutSession.status を completed に更新.

        type に応じて対応する History も作成する。
        """
        session_id = data["id"]  # type: ignore[index]
        checkout = CheckoutSession.objects.filter(stripe_session_id=session_id).first()
        if not checkout:
            logger.warning("CheckoutSession not found: session_id=%s", session_id)
            return

        # CheckoutSession のステータス更新
        checkout.status = "completed"
        checkout.save()
        logger.info("CheckoutSession completed: session_id=%s, type=%s", session_id, checkout.type)

        # type に応じて History を作成
        if checkout.type == "credit":
            StripeWebhookService._create_credit_history(checkout)  # noqa: SLF001
        elif checkout.type == "custom":
            StripeWebhookService._create_invoice_history(checkout)  # noqa: SLF001

    @staticmethod
    def _create_credit_history(checkout: CheckoutSession) -> None:
        """クレジット購入の CreditHistory を作成.

        1. Stripe API で Session を取得し payment_intent_id と price_id を特定
        2. CreditPlan を特定して CreditHistory を作成
        """
        try:
            session = stripe.checkout.Session.retrieve(
                checkout.stripe_session_id, expand=["line_items"]
            )
        except Exception:
            logger.exception("Failed to retrieve Session: session_id=%s", checkout.stripe_session_id)
            raise
        payment_intent_id = session.payment_intent
        price_id = session.line_items.data[0].price.id  # type: ignore[union-attr]

        try:
            credit_plan = CreditPlan.objects.get(stripe_price_id=price_id)
        except CreditPlan.DoesNotExist:
            logger.warning("CreditPlan not found: price_id=%s", price_id)
            return

        _, created = CreditHistory.objects.get_or_create(
            stripe_payment_id=payment_intent_id,
            defaults={
                "stripe_customer": checkout.stripe_customer,
                "credit_plan": credit_plan,
            },
        )
        if created:
            logger.info("CreditHistory created: payment_id=%s", payment_intent_id)
        else:
            logger.info("CreditHistory already exists: payment_id=%s", payment_intent_id)

    @staticmethod
    def _create_invoice_history(checkout: CheckoutSession) -> None:
        """カスタム支払いの InvoiceHistory を作成.

        1. Stripe API で Session を取得し payment_intent_id と商品情報を特定
        2. InvoiceHistory を作成
        """
        try:
            session = stripe.checkout.Session.retrieve(
                checkout.stripe_session_id, expand=["line_items"]
            )
        except Exception:
            logger.exception("Failed to retrieve Session: session_id=%s", checkout.stripe_session_id)
            raise
        payment_intent_id = session.payment_intent
        line_item = session.line_items.data[0]  # type: ignore[union-attr]
        description = line_item.description or "カスタム支払い"
        amount = line_item.amount_total

        _, created = InvoiceHistory.objects.get_or_create(
            stripe_payment_id=payment_intent_id,
            defaults={
                "stripe_customer": checkout.stripe_customer,
                "description": description,
                "amount": amount,
            },
        )
        if created:
            logger.info("InvoiceHistory created: payment_id=%s, amount=%s", payment_intent_id, amount)
        else:
            logger.info("InvoiceHistory already exists: payment_id=%s", payment_intent_id)

    # ========================================
    # subscription 系
    # ========================================

    @staticmethod
    def handle_subscription_created(data: object) -> None:
        """サブスク契約時: SubscriptionHistory を INSERT."""
        stripe_customer_id = data["customer"]  # type: ignore[index]
        stripe_subscription_id = data["id"]  # type: ignore[index]

        # Stripe API から最新のサブスク情報を取得
        try:
            sub = stripe.Subscription.retrieve(stripe_subscription_id)
        except Exception:
            logger.exception("Failed to retrieve Subscription: subscription_id=%s", stripe_subscription_id)
            raise
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]

        try:
            stripe_customer = StripeCustomer.objects.get(stripe_customer_id=stripe_customer_id)
            plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
        except (StripeCustomer.DoesNotExist, SubscriptionPlan.DoesNotExist):
            logger.warning("SubscriptionHistory skipped: customer=%s, price=%s not found", stripe_customer_id, price_id)
            return

        period_start = datetime.fromtimestamp(item["current_period_start"], tz=UTC)
        period_end = datetime.fromtimestamp(item["current_period_end"], tz=UTC)

        _, created = SubscriptionHistory.objects.update_or_create(
            stripe_subscription_id=stripe_subscription_id,
            defaults={
                "stripe_customer": stripe_customer,
                "subscription_plan": plan,
                "status": "created",
                "current_period_start": period_start,
                "current_period_end": period_end,
            },
        )
        if created:
            logger.info("SubscriptionHistory created: subscription_id=%s", stripe_subscription_id)
        else:
            logger.info("SubscriptionHistory already exists (updated): subscription_id=%s", stripe_subscription_id)

    @staticmethod
    def handle_subscription_updated(data: object) -> None:
        """サブスク更新時: SubscriptionHistory を UPDATE."""
        stripe_subscription_id = data["id"]  # type: ignore[index]

        # Stripe API から最新のサブスク情報を取得
        try:
            sub = stripe.Subscription.retrieve(stripe_subscription_id)
        except Exception:
            logger.exception("Failed to retrieve Subscription: subscription_id=%s", stripe_subscription_id)
            raise
        item = sub["items"]["data"][0]

        period_start = datetime.fromtimestamp(item["current_period_start"], tz=UTC)
        period_end = datetime.fromtimestamp(item["current_period_end"], tz=UTC)

        SubscriptionHistory.objects.filter(
            stripe_subscription_id=stripe_subscription_id
        ).update(
            status="updated",
            current_period_start=period_start,
            current_period_end=period_end,
        )
        logger.info("SubscriptionHistory updated: subscription_id=%s", stripe_subscription_id)

    @staticmethod
    def handle_subscription_deleted(data: object) -> None:
        """サブスク解約時: SubscriptionHistory.status を deleted に UPDATE."""
        stripe_subscription_id = data["id"]  # type: ignore[index]
        SubscriptionHistory.objects.filter(
            stripe_subscription_id=stripe_subscription_id
        ).update(status="deleted")
        logger.info("SubscriptionHistory deleted: subscription_id=%s", stripe_subscription_id)

    # ========================================
    # charge.refunded
    # ========================================

    @staticmethod
    def handle_charge_refunded(data: object) -> None:
        """返金時: CreditHistory / InvoiceHistory の status を refunded に UPDATE.

        charge.refunded の data から payment_intent を取得し、
        該当する History の status を更新する。
        """
        payment_intent_id = data["payment_intent"]  # type: ignore[index]

        # CreditHistory から探す
        updated = CreditHistory.objects.filter(
            stripe_payment_id=payment_intent_id
        ).update(status="refunded")

        if updated:
            logger.info("CreditHistory refunded: payment_id=%s", payment_intent_id)
            return

        # CreditHistory になければ InvoiceHistory を探す
        updated = InvoiceHistory.objects.filter(
            stripe_payment_id=payment_intent_id
        ).update(status="refunded")

        if updated:
            logger.info("InvoiceHistory refunded: payment_id=%s", payment_intent_id)
        else:
            logger.warning("Refund target not found: payment_id=%s", payment_intent_id)
