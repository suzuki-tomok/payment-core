from datetime import UTC, datetime

import stripe
from django.conf import settings

from ..models import (
    CheckoutSession,
    Company,
    CreditHistory,
    CreditPlan,
    StripeCustomer,
    SubscriptionHistory,
    SubscriptionPlan,
)

stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:
    """Stripe 関連のビジネスロジック."""

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
            # Stripe に Customer を作成
            customer = stripe.Customer.create(name=company.name)
            # Stripe から cus_xxx が返ってきてから DB に保存
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
        session = stripe.checkout.Session.create(
            customer=stripe_customer.stripe_customer_id,
            mode="subscription",
            line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
            success_url=f"{base_url}checkout/success/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}checkout/cancel/",
        )
        CheckoutSession.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id=session.id,
            type="subscription",
        )
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
        session = stripe.checkout.Session.create(
            customer=stripe_customer.stripe_customer_id,
            mode="payment",
            line_items=[{"price": credit_plan.stripe_price_id, "quantity": 1}],
            success_url=f"{base_url}checkout/success/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}checkout/cancel/",
        )
        CheckoutSession.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id=session.id,
            type="credit",
        )
        return session

    # ========================================
    # Webhook
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

    @staticmethod
    def handle_checkout_completed(data: object) -> None:
        """Checkout 完了時: CheckoutSession.status を completed に更新.

        type=credit の場合は CreditHistory も作成する。
        session_id で確実に自分の CheckoutSession と紐づくため、
        イベント到着順序の問題が起きない。
        """
        session_id = data["id"]  # type: ignore[index]
        checkout = CheckoutSession.objects.filter(stripe_session_id=session_id).first()
        if not checkout:
            return

        # ステータス更新
        checkout.status = "completed"
        checkout.save()

        # クレジット購入の場合は CreditHistory も作成
        if checkout.type == "credit":
            StripeService._create_credit_history(checkout)  # noqa: SLF001

    @staticmethod
    def _create_credit_history(checkout: CheckoutSession) -> None:
        """クレジット購入の CreditHistory を作成.

        1. Stripe API で Session を取得し payment_intent_id と price_id を特定
        2. CreditPlan を特定して CreditHistory を作成
        """
        session = stripe.checkout.Session.retrieve(
            checkout.stripe_session_id, expand=["line_items"]
        )
        payment_intent_id = session.payment_intent
        price_id = session.line_items.data[0].price.id  # type: ignore[union-attr]

        try:
            credit_plan = CreditPlan.objects.get(stripe_price_id=price_id)
        except CreditPlan.DoesNotExist:
            return

        # 重複防止: stripe_payment_id が同じなら作成しない
        CreditHistory.objects.get_or_create(
            stripe_payment_id=payment_intent_id,
            defaults={
                "stripe_customer": checkout.stripe_customer,
                "credit_plan": credit_plan,
            },
        )

    @staticmethod
    def _create_subscription_history(data: object, status: str) -> None:
        """SubscriptionHistory を1件 INSERT する共通処理.

        1. Stripe の customer ID から StripeCustomer を取得
        2. price ID から SubscriptionPlan を特定
        3. SubscriptionHistory を INSERT（常に新規レコード）
        """
        stripe_customer_id = data["customer"]  # type: ignore[index]
        stripe_subscription_id = data["id"]  # type: ignore[index]

        # Stripe API から最新のサブスク情報を取得（ペイロードにフィールドがない場合の対策）
        sub = stripe.Subscription.retrieve(stripe_subscription_id)
        # API 2025-03-31 以降: period は items.data[0] に移動
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]

        try:
            stripe_customer = StripeCustomer.objects.get(stripe_customer_id=stripe_customer_id)
            plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
        except (StripeCustomer.DoesNotExist, SubscriptionPlan.DoesNotExist):
            return

        period_start = datetime.fromtimestamp(item["current_period_start"], tz=UTC)
        period_end = datetime.fromtimestamp(item["current_period_end"], tz=UTC)

        SubscriptionHistory.objects.create(
            stripe_customer=stripe_customer,
            subscription_plan=plan,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            current_period_start=period_start,
            current_period_end=period_end,
        )

    @staticmethod
    def handle_subscription_created(data: object) -> None:
        """サブスク契約時: SubscriptionHistory を INSERT."""
        StripeService._create_subscription_history(data, data["status"])  # type: ignore[index]  # noqa: SLF001

    @staticmethod
    def handle_subscription_updated(data: object) -> None:
        """サブスク更新時（月次更新/プラン変更）: SubscriptionHistory を INSERT."""
        StripeService._create_subscription_history(data, data["status"])  # type: ignore[index]  # noqa: SLF001

    @staticmethod
    def handle_subscription_deleted(data: object) -> None:
        """サブスク解約時: status=canceled で SubscriptionHistory を INSERT."""
        StripeService._create_subscription_history(data, "canceled")  # noqa: SLF001

