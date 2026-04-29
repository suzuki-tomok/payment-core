"""Stripe Checkout を使った決済の起票と状態取得.

設計:
    - StripeClient (apps.py で DI 済) を get_stripe_client() で取得.
      service は stripe.* を直接 import しない (boundary は stripe/ 配下).
    - 外部 API call (Customer 作成 / Session 作成) と DB 書き込みが交互するため
      transaction.atomic は使わない. race condition は IntegrityError で個別に処理.
    - PaymentSystemError / PaymentConfigError は StripeClient 経由で素通しする
      (catch しない). caller 側で必要に応じて捕捉する.
    - URL routing は service の責務外. success_url / cancel_url は caller (view) が
      reverse() + urlencode() で組み立てて引数で渡す.
"""

import logging
from enum import StrEnum

from django.db import IntegrityError

from payment.models import Payment, StripeCustomer
from payment.stripe import (
    CreateCheckoutSessionInput,
    CreateCustomerInput,
    get_stripe_client,
)

from .dtos import CheckoutInput
from .exceptions import DuplicateOrderError

logger = logging.getLogger(__name__)


class PaymentStatus(StrEnum):
    """payment app が外部に公開する決済状態.

    内部 2 カラム (Payment.session_status / Payment.payment_status) を 1 値に集約した
    公開 view. caller はこちらだけ見れば良い.
    """

    NOT_FOUND = "not_found"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"


def create_checkout_url(input: CheckoutInput) -> str:
    """決済を起票し、ユーザーをリダイレクトする Stripe Checkout URL を返す.

    input.success_url / input.cancel_url は caller (view) が reverse() + urlencode()
    で組み立てた絶対 URL を渡す (URL routing は service の責務外).

    Raises:
        DuplicateOrderError: 同じ order_id で既に起票済み.
        PaymentSystemError: Stripe 一時障害 (rate limit, network, server). リトライ可能.
        PaymentConfigError: Stripe 恒久エラー (auth, invalid request, idempotency mismatch).

    Note:
        プログラミングエラー (TypeError, AttributeError 等) や想定外の例外は
        wrap せずそのまま propagate する.
    """
    # 1. 二重起票チェック (race condition の早期検知. race 自体は 4. の IntegrityError で防御)
    if Payment.objects.filter(order_id=input.order_id).exists():
        raise DuplicateOrderError(input.order_id)

    client = get_stripe_client()

    # 2. StripeCustomer 取得 or 作成 (company_id 単位で 1 個)
    customer = StripeCustomer.objects.filter(company_id=input.company_id).first()
    if customer is None:
        # 2a. Stripe 側で Customer 作成. idempotency_key で同 company の重複作成を防ぐ.
        # PaymentSystemError / PaymentConfigError はここから propagate.
        stripe_customer_id = client.create_customer(CreateCustomerInput(
            name=input.company_name,
            idempotency_key=f"customer-{input.company_id}",
        ))

        # 2b. ローカル DB に保存. race 時 (別 thread が先に作成済) は IntegrityError で
        # 取得し直す. Stripe 側は idempotency_key で同 customer が返るため孤児なし.
        try:
            customer = StripeCustomer.objects.create(
                company_id=input.company_id,
                company_name=input.company_name,
                stripe_customer_id=stripe_customer_id,
            )
        except IntegrityError:
            customer = StripeCustomer.objects.get(company_id=input.company_id)

    # 3. Stripe Checkout Session 作成. idempotency_key で同 order_id の重複作成を防ぐ.
    result = client.create_checkout_session(CreateCheckoutSessionInput(
        customer_id=customer.stripe_customer_id,
        amount=input.amount,
        description=input.description,
        success_url=input.success_url,
        cancel_url=input.cancel_url,
        idempotency_key=f"checkout-{input.order_id}",
    ))

    # 4. Payment レコード作成. race 時 (1. の通過後に別 thread が先に作成) は
    # IntegrityError → DuplicateOrderError に変換. Stripe 側は idempotency_key で
    # 同じ Session が返るため孤児なし.
    try:
        Payment.objects.create(
            stripe_customer=customer,
            order_id=input.order_id,
            stripe_session_id=result.session_id,
            stripe_payment_id=result.payment_intent_id,
            amount=input.amount,
            description=input.description,
        )
    except IntegrityError as e:
        raise DuplicateOrderError(input.order_id) from e

    logger.info(
        "Checkout created: order_id=%s session_id=%s customer_id=%s",
        input.order_id, result.session_id, customer.stripe_customer_id,
    )
    return result.url


def get_payment_status(order_id: str) -> PaymentStatus:
    """order_id の決済状態を返す. 未発見は PaymentStatus.NOT_FOUND.

    内部 2 カラム (session_status / payment_status) を公開 PaymentStatus 1 値に集約する.

    Note:
        この関数は基本的に例外を投げない (DB 取得のみ).
        DB 接続エラー等の想定外例外は wrap せず propagate する.
    """
    # 1. Payment 取得 (status 2 カラムだけ select)
    payment = Payment.objects.filter(order_id=order_id).only(
        "session_status", "payment_status",
    ).first()
    if payment is None:
        return PaymentStatus.NOT_FOUND

    # 2. payment_status を優先 (確定状態. 完了後返金 = REFUNDED は SUCCEEDED より新しい真実).
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
