"""payment app の公開例外. consumer はここから import する."""


class PaymentError(Exception):
    """payment app 例外の基底. consumer はこれを catch すれば全例外を拾える."""


class DuplicateOrderError(PaymentError):
    """同じ order_id で既に決済が起票済み (二重起票). リトライ無意味."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"order_id already exists: {order_id}")


class InvalidInputError(PaymentError):
    """CheckoutInput のバリデーションエラー (空文字 / 非正値など)."""


class PaymentSystemError(PaymentError):
    """一時的な障害 (Stripe ダウン、ネットワーク、レート制限). リトライ可能."""


class PaymentConfigError(PaymentError):
    """恒久的なエラー (APIキー無効、リクエスト不正、idempotency 衝突). 開発者対応必要."""
