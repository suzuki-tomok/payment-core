"""payment app の business 例外.

`payment.stripe.exceptions` (Stripe SDK 例外の翻訳) とは別物:
    - こちら: 業務ロジック由来 (二重起票, 入力不正)
    - あちら: Stripe API 由来 (一時障害, 設定エラー, webhook 署名)

caller (view 等) は両方の namespace から必要なものを import する.
"""


class DuplicateOrderError(Exception):
    """同じ order_id で既に決済が起票済み (二重起票). リトライ無意味."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"order_id already exists: {order_id}")


class InvalidInputError(Exception):
    """CheckoutInput のバリデーションエラー (空文字 / 非正値など)."""
