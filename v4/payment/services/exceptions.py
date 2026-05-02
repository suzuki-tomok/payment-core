"""payment app の business 例外.

service (DTO / handler) が raise する例外.
セクション label は「{起因} → {受け手}」:
    - 起因 = 論理的な発生源 (consumer の入力 / Stripe webhook 等)
    - 受け手 = 我々のコードの catch 層 (view)
    - 括弧 = 最終的な HTTP / 対処方針

`payment.stripe.exceptions` (Stripe SDK 例外の翻訳) とは別物:
    - こちら: 業務ロジック由来 (入力不正 / webhook 契約違反)
    - あちら: Stripe API 由来 (一時障害, 設定エラー, webhook 署名)

二重起票検知 (DuplicateOrderError) は不要な設計 (Stripe 側 idempotency_key +
webhook handler の get_or_create で担保するため).
"""

# =============================================================================
# 入力起因: consumer → view (HTTP 400 で caller に修正させる)
# =============================================================================


class InvalidInputError(Exception):
    """CheckoutInput のバリデーションエラー (空文字 / 非正値など)."""


# =============================================================================
# Webhook 起因: Stripe → view (HTTP 500 + 運用 alert)
# =============================================================================


class WebhookContractError(Exception):
    """webhook event payload が我々の前提を破った場合.

    例:
        - metadata.order_id 不在 (我々が起票した Session なら必ず入っているはず)
        - data.customer 不在 (mode=payment Session なら必ず入っているはず)
        - data.customer に対応する StripeCustomer が DB に無い

    スルーするのはセキュリティ的に怪しい (我々のバグを潰す可能性) ので明示的に raise し、
    view 側で 500 を返して Stripe にリトライさせる + 運用 alert を発火させる.
    """
