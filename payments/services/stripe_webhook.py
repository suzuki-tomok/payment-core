import logging
from datetime import UTC, datetime

import stripe
from django.conf import settings
from django.db import transaction

from ..models import (
    CheckoutSessionStatus,
    CreditPlan,
    CreditStatus,
    InvoiceStatus,
    StripeCustomer,
    SubscriptionPlan,
    SubscriptionStatus,
)

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeWebhookService:
    """Stripe Webhook のハンドラ."""

    @staticmethod
    def verify_webhook(payload: bytes, sig_header: str) -> dict:  # type: ignore[type-arg]
        """Webhook の署名を検証してイベントを返す."""
        return stripe.Webhook.construct_event(  # type: ignore[return-value]
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )

    # ========================================
    # checkout.session.completed
    # ========================================

    @staticmethod
    def handle_checkout_completed(data: object) -> None:
        """Checkout 完了時: CheckoutSessionStatus.status を completed に更新.

        type に応じて対応する History も作成する。
        """
        session_id = data["id"]  # type: ignore[index]
        checkout = CheckoutSessionStatus.objects.filter(stripe_session_id=session_id).first()
        if not checkout:
            logger.warning("CheckoutSessionStatus not found: session_id=%s", session_id)
            return

        with transaction.atomic():
            checkout.status = "completed"
            checkout.save()
            cid = checkout.stripe_customer.stripe_customer_id
            logger.info("Checkout completed: sid=%s type=%s cus=%s", session_id, checkout.type, cid)

            if checkout.type == "credit":
                StripeWebhookService._create_credit_history(checkout)  # noqa: SLF001
            elif checkout.type == "custom":
                StripeWebhookService._create_invoice_history(checkout)  # noqa: SLF001

    @staticmethod
    def handle_checkout_expired(data: object) -> None:
        """Checkout 期限切れ: CheckoutSessionStatus.status を expired に更新."""
        session_id = data["id"]  # type: ignore[index]
        checkout = CheckoutSessionStatus.objects.filter(stripe_session_id=session_id).first()
        if not checkout:
            logger.warning("CheckoutSessionStatus not found: session_id=%s", session_id)
            return

        checkout.status = "expired"
        checkout.save()
        cid = checkout.stripe_customer.stripe_customer_id
        logger.info("Checkout expired: sid=%s cus=%s", session_id, cid)

    @staticmethod
    def _create_credit_history(checkout: CheckoutSessionStatus) -> None:
        """クレジット購入の CreditStatus を作成."""
        session = stripe.checkout.Session.retrieve(
            checkout.stripe_session_id, expand=["line_items"]
        )
        payment_intent_id = str(session.payment_intent)
        price_id = session.line_items.data[0].price.id  # type: ignore[union-attr]

        try:
            credit_plan = CreditPlan.objects.get(stripe_price_id=price_id)
        except CreditPlan.DoesNotExist:
            logger.warning("CreditPlan not found: price_id=%s", price_id)
            return

        CreditStatus.objects.create(
            stripe_payment_id=payment_intent_id,
            stripe_customer=checkout.stripe_customer,
            credit_plan=credit_plan,
        )
        cid = checkout.stripe_customer.stripe_customer_id
        logger.info("CreditStatus created: pid=%s cus=%s", payment_intent_id, cid)

    @staticmethod
    def _create_invoice_history(checkout: CheckoutSessionStatus) -> None:
        """カスタム支払いの InvoiceStatus を作成."""
        session = stripe.checkout.Session.retrieve(
            checkout.stripe_session_id, expand=["line_items"]
        )
        payment_intent_id = str(session.payment_intent)
        line_item = session.line_items.data[0]  # type: ignore[union-attr]
        description = line_item.description or "カスタム支払い"
        amount = line_item.amount_total

        InvoiceStatus.objects.create(
            stripe_payment_id=payment_intent_id,
            stripe_customer=checkout.stripe_customer,
            description=description,
            amount=amount,
        )
        cid = checkout.stripe_customer.stripe_customer_id
        logger.info("InvoiceStatus created: pid=%s cus=%s", payment_intent_id, cid)

    # ========================================
    # subscription 系
    # ========================================

    @staticmethod
    def handle_subscription_created(data: object) -> None:
        """サブスク契約時: SubscriptionStatus を作成."""
        stripe_customer_id = data["customer"]  # type: ignore[index]
        stripe_subscription_id = data["id"]  # type: ignore[index]

        sub = stripe.Subscription.retrieve(stripe_subscription_id)
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]

        try:
            stripe_customer = StripeCustomer.objects.get(stripe_customer_id=stripe_customer_id)
            plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
        except (StripeCustomer.DoesNotExist, SubscriptionPlan.DoesNotExist):
            logger.warning("SubscriptionStatus skipped: customer=%s, price=%s", stripe_customer_id, price_id)
            return

        period_start = datetime.fromtimestamp(item["current_period_start"], tz=UTC)
        period_end = datetime.fromtimestamp(item["current_period_end"], tz=UTC)

        SubscriptionStatus.objects.create(
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer=stripe_customer,
            subscription_plan=plan,
            status=sub["status"],
            current_period_start=period_start,
            current_period_end=period_end,
        )
        logger.info("SubStatus created: sub=%s cus=%s", stripe_subscription_id, stripe_customer_id)

    @staticmethod
    def handle_subscription_updated(data: object) -> None:
        """サブスク更新時: SubscriptionStatus を UPDATE.

        プラン変更・月次更新の両方に対応。
        price_id から SubscriptionPlan を特定し、プランも更新する。
        """
        stripe_subscription_id = data["id"]  # type: ignore[index]

        sub = stripe.Subscription.retrieve(stripe_subscription_id)
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]

        period_start = datetime.fromtimestamp(item["current_period_start"], tz=UTC)
        period_end = datetime.fromtimestamp(item["current_period_end"], tz=UTC)

        # プラン変更に対応: price_id から SubscriptionPlan を取得
        try:
            plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
        except SubscriptionPlan.DoesNotExist:
            logger.warning("SubscriptionPlan not found: price_id=%s", price_id)
            return

        SubscriptionStatus.objects.filter(
            stripe_subscription_id=stripe_subscription_id
        ).update(
            subscription_plan=plan,
            status=sub["status"],
            current_period_start=period_start,
            current_period_end=period_end,
        )
        stripe_customer_id = data["customer"]  # type: ignore[index]
        logger.info("SubStatus updated: sub=%s plan=%s cus=%s", stripe_subscription_id, plan.name, stripe_customer_id)

    @staticmethod
    def handle_subscription_deleted(data: object) -> None:
        """サブスク解約時: SubscriptionStatus.status を canceled に UPDATE."""
        stripe_subscription_id = data["id"]  # type: ignore[index]
        SubscriptionStatus.objects.filter(
            stripe_subscription_id=stripe_subscription_id
        ).update(status="canceled")
        stripe_customer_id = data["customer"]  # type: ignore[index]
        logger.info("SubStatus canceled: sub=%s cus=%s", stripe_subscription_id, stripe_customer_id)

    # ========================================
    # charge.refunded
    # ========================================

    @staticmethod
    def handle_charge_refunded(data: object) -> None:
        """返金時: CreditStatus / InvoiceStatus の status を refunded に UPDATE."""
        payment_intent_id = data["payment_intent"]  # type: ignore[index]

        stripe_customer_id = data["customer"]  # type: ignore[index]

        updated = CreditStatus.objects.filter(
            stripe_payment_id=payment_intent_id
        ).update(status="refunded")
        if updated:
            logger.info("CreditStatus refunded: pid=%s cus=%s", payment_intent_id, stripe_customer_id)
            return

        updated = InvoiceStatus.objects.filter(
            stripe_payment_id=payment_intent_id
        ).update(status="refunded")
        if updated:
            logger.info("InvoiceStatus refunded: pid=%s cus=%s", payment_intent_id, stripe_customer_id)
        else:
            logger.warning("Refund target not found: pid=%s cus=%s", payment_intent_id, stripe_customer_id)
