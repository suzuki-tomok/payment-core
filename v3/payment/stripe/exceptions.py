"""Stripe SDK 例外を service 層向けに翻訳した型.

StripeClient が stripe.* 例外を catch してこれらに raise し直す.
service 側はこの 3 種類だけ扱えばよい (stripe.* に依存しない).
"""


class PaymentSystemError(Exception):
    """一時的な障害 (Stripe ダウン、ネットワーク、レート制限). リトライ可能."""


class PaymentConfigError(Exception):
    """恒久的なエラー (APIキー無効、リクエスト不正、idempotency 衝突). 開発者対応必要."""


class WebhookSignatureError(Exception):
    """Webhook 署名検証失敗 / payload 不正. リトライ無意味 (HTTP 400 を返す)."""
