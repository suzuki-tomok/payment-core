"""Stripe SDK 例外を service 層向けに翻訳した型.

StripeClient (gateway) が stripe.* 例外を catch してこれらに raise し直す.
セクション label は「{起因} → {受け手}」:
    - 起因 = 論理的な発生源 (Stripe / consumer 等)
    - 受け手 = 我々のコードの catch 層 (service / view)
    - 括弧 = 最終的な HTTP / 対処方針
"""

# =============================================================================
# Stripe API 起因: Stripe → service (一時 = caller リトライ可 / 恒久 = 開発者対応)
# =============================================================================


class PaymentSystemError(Exception):
    """一時的な障害 (Stripe ダウン、ネットワーク、レート制限). リトライ可能."""


class PaymentConfigError(Exception):
    """恒久的なエラー (APIキー無効、リクエスト不正、idempotency 衝突). 開発者対応必要."""


# =============================================================================
# Webhook 起因: Stripe → view (HTTP 400 で Stripe にリトライさせない)
# =============================================================================


class WebhookSignatureError(Exception):
    """Webhook 署名検証失敗 / payload 不正. リトライ無意味 (HTTP 400 を返す)."""
