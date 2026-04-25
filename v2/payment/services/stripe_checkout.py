"""Stripe Checkout 関連の実装. 公開は payment.api 経由 (これを直接 import しない)."""

import logging

import stripe
from django.conf import settings
from django.db import IntegrityError
from django.urls import reverse

from payment.dto import CheckoutInput
from payment.enums import PaymentStatus
from payment.exceptions import (
    DuplicateOrderError,
    PaymentConfigError,
    PaymentSystemError,
)
from payment.models import Payment, StripeCustomer

logger = logging.getLogger(__name__)


class StripeCheckoutService:
    """Stripe Checkout を使った決済操作の実装."""

    @staticmethod
    def create_checkout_url(input: CheckoutInput) -> str:
        """決済を起票し、ユーザーをリダイレクトする Stripe Checkout URL を返す.

        Raises:
            DuplicateOrderError: 同じ order_id で既に起票済み.
            PaymentSystemError: Stripe 一時障害 (rate limit, network, server). リトライ可能.
            PaymentConfigError: Stripe 恒久エラー (auth, invalid request, idempotency mismatch).

        Note:
            上記 PaymentError 階層は「既知ケース」として保証する例外.
            プログラミングエラー (TypeError, AttributeError 等) や想定外の例外は
            wrap せずそのまま propagate する.
        """
        # 1. 二重起票チェック (race condition 対策の早期検知)
        if Payment.objects.filter(order_id=input.order_id).exists():
            raise DuplicateOrderError(input.order_id)

        # 2. StripeCustomer 取得 or 作成
        customer = StripeCustomer.objects.filter(company_id=input.company_id).first()
        if customer is None:
            # 2a. Stripe 側で Customer 作成 (idempotency_key で同 company の重複防止)
            try:
                stripe_customer = stripe.Customer.create(
                    name=input.company_name,
                    idempotency_key=f"customer-{input.company_id}",
                )
            except (stripe.RateLimitError, stripe.APIConnectionError, stripe.APIError) as e:
                # 一時障害 (リトライ可)
                logger.warning("Stripe transient: req=%s type=%s", e.request_id, type(e).__name__)
                raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
            except (stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError) as e:
                # 恒久エラー (リトライ無意味)
                logger.error(
                    "Stripe permanent: req=%s type=%s code=%s",
                    e.request_id, type(e).__name__, getattr(e, "code", None),
                )
                raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
            except stripe.StripeError as e:
                # 想定外
                logger.exception("Stripe unexpected: req=%s type=%s", e.request_id, type(e).__name__)
                raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e

            # 2b. ローカル DB に保存 (race 時は別 thread が先に作っているので取得し直し)
            try:
                customer = StripeCustomer.objects.create(
                    company_id=input.company_id,
                    company_name=input.company_name,
                    stripe_customer_id=stripe_customer.id,
                )
            except IntegrityError:
                customer = StripeCustomer.objects.get(company_id=input.company_id)

        # 3. Stripe からのリダイレクト URL 組み立て
        base_url = settings.PAYMENT_BASE_URL.rstrip("/")
        success_url = f"{base_url}{reverse('payment:checkout_success')}?order_id={input.order_id}"
        cancel_url = f"{base_url}{reverse('payment:checkout_cancel')}?order_id={input.order_id}"

        # 4. Stripe Checkout Session 作成 (idempotency_key で同 order_id の重複防止)
        try:
            session = stripe.checkout.Session.create(
                customer=customer.stripe_customer_id,
                mode="payment",
                line_items=[{
                    "price_data": {
                        "currency": "jpy",
                        "unit_amount": input.amount,
                        "product_data": {"name": input.description},
                    },
                    "quantity": 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                idempotency_key=f"checkout-{input.order_id}",
            )
        except (stripe.RateLimitError, stripe.APIConnectionError, stripe.APIError) as e:
            # 一時障害 (リトライ可)
            logger.warning("Stripe transient: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        except (stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError) as e:
            # 恒久エラー (リトライ無意味)
            logger.error(
                "Stripe permanent: req=%s type=%s code=%s",
                e.request_id, type(e).__name__, getattr(e, "code", None),
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        except stripe.StripeError as e:
            # 想定外
            logger.exception("Stripe unexpected: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e

        # 5. Payment レコード作成 (race 時は IntegrityError → DuplicateOrderError に変換)
        # session.payment_intent は str | PaymentIntent | None だが mode=payment のため str が返る
        # session.url は str | None だが新規作成時は必ず str が返る
        try:
            Payment.objects.create(
                stripe_customer=customer,
                order_id=input.order_id,
                stripe_session_id=session.id,
                stripe_payment_id=str(session.payment_intent),
                amount=input.amount,
                description=input.description,
            )
        except IntegrityError as e:
            # Stripe 側は idempotency_key で同じ Session が返るため孤児なし
            raise DuplicateOrderError(input.order_id) from e

        assert session.url is not None  # noqa: S101  Session.create 直後は必ず url が設定される
        return session.url

    @staticmethod
    def get_payment_status(order_id: str) -> PaymentStatus:
        """order_id の決済状態を返す. 未発見は PaymentStatus.NOT_FOUND.

        内部 2カラム (session_status / payment_status) を公開 PaymentStatus 1値に集約する.
        """
        # 1. Payment 取得 (status 2カラムだけ select)
        payment = Payment.objects.filter(order_id=order_id).only(
            "session_status", "payment_status",
        ).first()
        if payment is None:
            return PaymentStatus.NOT_FOUND

        # 2. payment_status 優先で確定状態を判定 (succeeded / refunded)
        if payment.payment_status == Payment.PaymentStatus.SUCCEEDED:
            return PaymentStatus.SUCCEEDED
        if payment.payment_status == Payment.PaymentStatus.REFUNDED:
            return PaymentStatus.REFUNDED

        # 3. session_status で lifecycle 終了状態を判定 (canceled / expired)
        if payment.session_status == Payment.SessionStatus.CANCELED:
            return PaymentStatus.CANCELED
        if payment.session_status == Payment.SessionStatus.EXPIRED:
            return PaymentStatus.EXPIRED

        # 4. 上記いずれも該当しなければ進行中
        return PaymentStatus.PENDING
