"""payment app の公開 API.

他の Django app は **このモジュールから import** すること.
内部実装 (services/, models/) は直接参照しないこと.

公開しているもの:
    - 公開関数: create_checkout_url, get_payment_status (実装は services/ に delegate)
    - 公開 DTO: CheckoutInput (定義は payment.dto)
    - 公開 enum: PaymentStatus (定義は payment.enums)
    - 公開例外: PaymentError とその subclass (定義は payment.exceptions)
"""

from payment.dto import CheckoutInput
from payment.enums import PaymentStatus
from payment.exceptions import (
    DuplicateOrderError,
    InvalidInputError,
    PaymentConfigError,
    PaymentError,
    PaymentSystemError,
)
from payment.services.stripe_checkout import StripeCheckoutService


def create_checkout_url(input: CheckoutInput) -> str:
    """決済を起票し、ユーザーをリダイレクトする Stripe Checkout URL を返す.

    Raises:
        InvalidInputError: CheckoutInput 構築時に空文字 / 非正値を渡した場合.
        DuplicateOrderError: 同じ order_id で既に起票済み.
        PaymentSystemError: Stripe 一時障害 (rate limit, network, server). リトライ可能.
        PaymentConfigError: Stripe 恒久エラー (auth, invalid request, idempotency mismatch).

    Note:
        上記 PaymentError 階層は payment app が「既知ケース」として保証する例外.
        プログラミングエラー (TypeError, AttributeError 等) や想定外の例外は
        wrap せずそのまま propagate する. caller 側で `except Exception` するか、
        Sentry 等の監視で拾う想定.
    """
    return StripeCheckoutService.create_checkout_url(input)


def get_payment_status(order_id: str) -> PaymentStatus:
    """order_id の決済状態を返す. 未発見は PaymentStatus.NOT_FOUND.

    Note:
        この関数は基本的に例外を投げない (DB 取得のみ).
        DB 接続エラー等の想定外例外は wrap せず propagate する.
    """
    return StripeCheckoutService.get_payment_status(order_id)


__all__ = [
    # types & enum
    "CheckoutInput",
    "PaymentStatus",
    # exceptions
    "DuplicateOrderError",
    "InvalidInputError",
    "PaymentConfigError",
    "PaymentError",
    "PaymentSystemError",
    # functions
    "create_checkout_url",
    "get_payment_status",
]
