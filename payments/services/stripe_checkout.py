import logging

import stripe
from django.conf import settings

from ..models import (
    CheckoutSession,
    Company,
    CreditPlan,
    StripeCustomer,
    SubscriptionPlan,
)

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeCheckoutService:
    """Stripe Customer 取得/作成 と Checkout Session 作成."""

    # ========================================
    # Customer
    # ========================================

    @staticmethod
    def get_or_create_customer(company: Company) -> StripeCustomer:
        """StripeCustomer を取得、なければ Stripe に作成.

        1. DB に StripeCustomer があればそれを返す
        2. なければ Stripe API で Customer を作成
        3. Stripe から cus_xxx が返ってきたら DB に StripeCustomer レコードを作成
        """
        try:
            return StripeCustomer.objects.get(company=company)
        except StripeCustomer.DoesNotExist:
            logger.info("Creating Stripe Customer for company=%s", company.name)
            try:
                customer = stripe.Customer.create(name=company.name)
            except Exception:
                logger.exception("Failed to create Stripe Customer for company=%s", company.name)
                raise
            return StripeCustomer.objects.create(
                company=company,
                stripe_customer_id=customer.id,
            )

    # ========================================
    # Checkout
    # ========================================

    @staticmethod
    def create_subscription_checkout(
        stripe_customer: StripeCustomer,
        plan: SubscriptionPlan,
        base_url: str,
    ) -> stripe.checkout.Session:
        """サブスクリプション用の Checkout Session を作成.

        1. Stripe に mode="subscription" で Session 作成
        2. DB に CheckoutSession を保存（status=pending）
        3. Session を返す（呼び出し元が session.url にリダイレクト）
        """
        try:
            session = stripe.checkout.Session.create(
                customer=stripe_customer.stripe_customer_id,
                mode="subscription",
                line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
                success_url=f"{base_url}checkout/success/?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}checkout/cancel/",
            )
        except Exception:
            logger.exception("Failed to create subscription checkout")
            raise
        CheckoutSession.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id=session.id,
            type="subscription",
        )
        logger.info("Subscription checkout created: session_id=%s", session.id)
        return session

    @staticmethod
    def create_credit_checkout(
        stripe_customer: StripeCustomer,
        credit_plan: CreditPlan,
        base_url: str,
    ) -> stripe.checkout.Session:
        """クレジット購入用の Checkout Session を作成.

        1. Stripe に mode="payment" で Session 作成（買い切り）
        2. DB に CheckoutSession を保存（status=pending）
        3. Session を返す（呼び出し元が session.url にリダイレクト）
        """
        try:
            session = stripe.checkout.Session.create(
                customer=stripe_customer.stripe_customer_id,
                mode="payment",
                line_items=[{"price": credit_plan.stripe_price_id, "quantity": 1}],
                success_url=f"{base_url}checkout/success/?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}checkout/cancel/",
            )
        except Exception:
            logger.exception("Failed to create credit checkout")
            raise
        CheckoutSession.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id=session.id,
            type="credit",
        )
        logger.info("Credit checkout created: session_id=%s", session.id)
        return session

    @staticmethod
    def create_custom_checkout(
        stripe_customer: StripeCustomer,
        amount: int,
        description: str,
        base_url: str,
    ) -> stripe.checkout.Session:
        """カスタム金額の Checkout Session を作成.

        1. アプリで計算した金額を price_data で動的に指定
        2. DB に CheckoutSession を保存（status=pending）
        3. Session を返す（呼び出し元が session.url にリダイレクト）
        """
        try:
            session = stripe.checkout.Session.create(
                customer=stripe_customer.stripe_customer_id,
                mode="payment",
                line_items=[{
                    "price_data": {
                        "currency": "jpy",
                        "unit_amount": amount,
                        "product_data": {"name": description},
                    },
                    "quantity": 1,
                }],
                success_url=f"{base_url}checkout/success/?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}checkout/cancel/",
            )
        except Exception:
            logger.exception("Failed to create custom checkout: amount=%d", amount)
            raise
        CheckoutSession.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id=session.id,
            type="custom",
        )
        logger.info("Custom checkout created: session_id=%s, amount=%d", session.id, amount)
        return session
