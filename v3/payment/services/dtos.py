"""payment app の公開 DTO.

service と caller (view 等) の間の契約.
`payment.stripe.dtos` (StripeClient と service の間の契約) とは別 namespace.
"""

from dataclasses import dataclass

from .exceptions import InvalidInputError


@dataclass(frozen=True)
class CheckoutInput:
    """create_checkout_url の入力. 構築時に __post_init__ でバリデーションする."""

    order_id: str
    """外部システムの取引 ID. payment app 内で一意 (二重起票防止)."""

    company_id: str
    """外部システムの会社 ID. StripeCustomer 紐付けキー."""

    company_name: str
    """Stripe Customer の name に渡す表示名. Stripe Dashboard / 領収書に表示される."""

    amount: int
    """決済金額 (円). 1 以上."""

    description: str
    """決済の説明. Stripe Checkout 画面 / 領収書に表示される."""

    success_url: str
    """決済成功時の戻り先 URL. caller (view) が reverse() + urlencode() で組み立てた絶対 URL."""

    cancel_url: str
    """決済キャンセル時の戻り先 URL. 同上."""

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise InvalidInputError("order_id is required")
        if not self.company_id.strip():
            raise InvalidInputError("company_id is required")
        if not self.company_name.strip():
            raise InvalidInputError("company_name is required")
        if not self.description.strip():
            raise InvalidInputError("description is required")
        if not self.success_url.strip():
            raise InvalidInputError("success_url is required")
        if not self.cancel_url.strip():
            raise InvalidInputError("cancel_url is required")
        if self.amount <= 0:
            raise InvalidInputError(f"amount must be positive, got {self.amount}")
