"""Stripe Checkout を使った決済の起票と状態取得.

設計:
    - StripeClient (apps.py で DI 済) を get_stripe_client() で取得.
      service は stripe.* を直接 import しない (boundary は stripe/ 配下).
    - 起票時には Payment を作らない. webhook (checkout.session.completed) で初めて作成する.
      これによりタブ閉じ等で詰まらない (idempotency_key の cache が同じ Session URL を返す).
    - 同 order_id でも amount が変われば別 Session 扱い (idempotency_key に amount を含める).
    - URL routing は service の責務外. success_url / cancel_url は caller (view) が
      reverse() + urlencode() で組み立てて引数で渡す.
    - PaymentSystemError / PaymentConfigError は StripeClient 経由で素通しする
      (catch しない). caller 側で必要に応じて捕捉する.
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

logger = logging.getLogger(__name__)


class PaymentStatus(StrEnum):
    """payment app が外部に公開する決済状態.

    「Payment レコード = 決済成功した事実」しか持たないため、
    pending / canceled / expired は全て NOT_PAID に集約される (= Payment 不在).
    """

    NOT_PAID = "not_paid"  # Payment 不在 (未決済 / キャンセル / 期限切れ全て含む)
    PAID = "paid"          # Payment 存在、is_refunded=False
    REFUNDED = "refunded"  # Payment 存在、is_refunded=True


def create_checkout_url(input: CheckoutInput) -> str:
    """Stripe Checkout URL を返す. DB に Payment は作らない.

    Customer 作成のみ DB 反映する (Stripe 側 Customer と紐付け). Payment は
    webhook 受信時に作成される.

    input.success_url / input.cancel_url は caller (view) が reverse() + urlencode()
    で組み立てた絶対 URL を渡す.

    idempotency_key は f"checkout-{order_id}-{amount}" 形式.
    - 同 order_id + 同 amount → Stripe cache hit → 同じ Session URL (24h以内なら続行可)
    - 同 order_id で amount 変更 → 別 key → 新 Session 作成

    Raises:
        PaymentSystemError: Stripe 一時障害 (rate limit, network, server). リトライ可能.
        PaymentConfigError: Stripe 恒久エラー (auth, invalid request). 開発者対応必要.

    Note:
        DuplicateOrderError は raise しない (起票時の重複検知をしない設計).
        二重決済防止は Stripe 側の idempotency_key + 我々の webhook handler の
        Payment.get_or_create で担保する.
    """
    client = get_stripe_client()

    # 1. StripeCustomer 取得 or 作成 (company_id 単位で 1 個)
    customer = StripeCustomer.objects.filter(company_id=input.company_id).first()
    if customer is None:
        # 1a. Stripe 側で Customer 作成. idempotency_key で同 company の重複作成を防ぐ.
        # PaymentSystemError / PaymentConfigError はここから propagate.
        stripe_customer_id = client.create_customer(CreateCustomerInput(
            name=input.company_name,
            idempotency_key=f"customer-{input.company_id}",
        ))

        # 1b. ローカル DB に保存. race 時 (別 thread が先に作成済) は IntegrityError で
        # 取得し直す. Stripe 側は idempotency_key で同 customer が返るため孤児なし.
        try:
            customer = StripeCustomer.objects.create(
                company_id=input.company_id,
                company_name=input.company_name,
                stripe_customer_id=stripe_customer_id,
            )
        except IntegrityError:
            customer = StripeCustomer.objects.get(company_id=input.company_id)

    # 2. Stripe Checkout Session 作成.
    # - idempotency_key に amount を含めて、amount 変更時は新 Session が作られるように.
    # - metadata に order_id を入れて webhook 受信時に逆引き可能にする.
    result = client.create_checkout_session(CreateCheckoutSessionInput(
        customer_id=customer.stripe_customer_id,
        amount=input.amount,
        description=input.description,
        success_url=input.success_url,
        cancel_url=input.cancel_url,
        idempotency_key=f"checkout-{input.order_id}-{input.amount}",
        metadata={"order_id": input.order_id},
    ))

    logger.info(
        "Checkout session prepared",
        extra={
            "order_id": input.order_id,
            "session_id": result.session_id,
            "customer_id": customer.stripe_customer_id,
        },
    )
    return result.url


def get_payment_status(order_id: str) -> PaymentStatus:
    """order_id の決済状態を返す. 未決済 / 決済済 / 返金済 の 3 値.

    Note:
        Payment レコード = 「決済成功した事実」のみなので、未決済 / キャンセル /
        期限切れは全て NOT_PAID として返される. これらを区別したい場合は Stripe
        Dashboard で order_id の metadata を検索する.
    """
    payment = Payment.objects.filter(order_id=order_id).only("is_refunded").first()
    if payment is None:
        return PaymentStatus.NOT_PAID
    return PaymentStatus.REFUNDED if payment.is_refunded else PaymentStatus.PAID
