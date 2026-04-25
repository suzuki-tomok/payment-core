"""payment app の公開 DTO."""

from dataclasses import dataclass

from payment.exceptions import InvalidInputError


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

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise InvalidInputError("order_id is required")
        if not self.company_id.strip():
            raise InvalidInputError("company_id is required")
        if not self.company_name.strip():
            raise InvalidInputError("company_name is required")
        if not self.description.strip():
            raise InvalidInputError("description is required")
        if self.amount <= 0:
            raise InvalidInputError(f"amount must be positive, got {self.amount}")
