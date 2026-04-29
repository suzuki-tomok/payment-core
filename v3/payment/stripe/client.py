"""StripeClient: Stripe SDK の薄いラッパー (gateway).

役割:
    - Stripe SDK の例外を payment app の PaymentError 階層に変換
    - service 側に必要なフィールドだけ DTO で返す (stripe.* オブジェクトを leak させない)
    - api_key / api_version の保持 (instance ごと)

service は stripe.* を直接 import せず、StripeClient のメソッドを呼ぶ.
テストでは Mock(spec=StripeClient) で差し替え可能.
"""

import logging

import stripe

from .dtos import (
    ConstructWebhookEventInput,
    ConstructWebhookEventOutput,
    CreateCheckoutSessionInput,
    CreateCheckoutSessionOutput,
    CreateCustomerInput,
    GetCompletedSessionDetailsOutput,
)
from .exceptions import (
    PaymentConfigError,
    PaymentSystemError,
    WebhookSignatureError,
)

logger = logging.getLogger(__name__)


class StripeClient:
    """Stripe SDK のラッパー. service に inject される."""

    def __init__(self, *, api_key: str, api_version: str) -> None:
        # stripe-python は API key / version を module-level の global に持つ仕様.
        # instance ごとに切り替えたいケースでは最後に作った instance の値が勝つ点に注意
        # (本アプリでは settings から 1 つだけ作るので問題なし).
        stripe.api_key = api_key
        stripe.api_version = api_version

    def create_customer(self, params: CreateCustomerInput) -> str:
        """Stripe Customer を作成. customer_id を返す.

        Raises:
            PaymentSystemError: 一時障害.
            PaymentConfigError: 恒久エラー.
        """
        try:
            # idempotency_key は同一キーでの再送 → 同一結果を保証 (重複作成防止).
            customer = stripe.Customer.create(
                name=params.name, idempotency_key=params.idempotency_key,
            )
        # 一時障害 (リトライで回復する可能性あり):
        #   RateLimitError       = 429 (短期スロットリング)
        #   APIConnectionError   = ネットワーク到達失敗
        #   APIError             = Stripe 側 5xx
        except (stripe.RateLimitError, stripe.APIConnectionError, stripe.APIError) as e:
            logger.warning("Stripe transient: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        # 恒久エラー (リトライしても直らない. 開発者対応必要):
        #   AuthenticationError  = API key 無効
        #   InvalidRequestError  = リクエスト不正 (パラメータ間違い等)
        #   IdempotencyError     = 同じ idempotency_key で異なるパラメータ送信
        except (
            stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError,
        ) as e:
            logger.error(
                "Stripe permanent: req=%s type=%s code=%s",
                e.request_id, type(e).__name__, getattr(e, "code", None),
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        # 上記以外の StripeError. 想定外なので一時障害扱いにフォールバック (logger.exception で stacktrace)
        except stripe.StripeError as e:
            logger.exception("Stripe unexpected: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e
        return customer.id

    def create_checkout_session(
        self, params: CreateCheckoutSessionInput,
    ) -> CreateCheckoutSessionOutput:
        """Stripe Checkout Session を作成 (mode=payment, JPY 固定).

        Raises:
            PaymentSystemError: 一時障害.
            PaymentConfigError: 恒久エラー.
        """
        try:
            # mode="payment" = 一回払い (subscription ではない).
            # currency="jpy" は本アプリの仕様で固定. 多通貨対応する時は params に持たせる.
            # line_items は 1 件固定 (free-amount custom payment 用途のため).
            session = stripe.checkout.Session.create(
                customer=params.customer_id,
                mode="payment",
                line_items=[{
                    "price_data": {
                        "currency": "jpy",
                        "unit_amount": params.amount,
                        "product_data": {"name": params.description},
                    },
                    "quantity": 1,
                }],
                success_url=params.success_url,
                cancel_url=params.cancel_url,
                idempotency_key=params.idempotency_key,
            )
        except (stripe.RateLimitError, stripe.APIConnectionError, stripe.APIError) as e:
            logger.warning("Stripe transient: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        except (
            stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError,
        ) as e:
            logger.error(
                "Stripe permanent: req=%s type=%s code=%s",
                e.request_id, type(e).__name__, getattr(e, "code", None),
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        except stripe.StripeError as e:
            logger.exception("Stripe unexpected: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e

        # mode=payment かつ Session.create 直後は url / payment_intent が必ず set される (Stripe API 仕様).
        # None なら Stripe API が契約を破ってるので恒久エラーとして surface (assert は -O で消えるので使わない).
        if session.url is None:
            raise PaymentConfigError("Stripe contract violation: session.url is None after create")
        # session.payment_intent の SDK 型は str | PaymentIntent | None. mode=payment 直後は str (ID) で返る.
        # None / 別型を素通しすると str(None)="None" や str(PaymentIntent obj)="<...>" が DB に入り、
        # 次の起票で stripe_payment_id unique 衝突を起こす. isinstance で str を保証する.
        if not isinstance(session.payment_intent, str):
            raise PaymentConfigError(
                "Stripe contract violation: session.payment_intent is not str after create",
            )
        return CreateCheckoutSessionOutput(
            session_id=session.id,
            payment_intent_id=session.payment_intent,
            url=session.url,
        )

    def get_completed_session_details(
        self, session_id: str,
    ) -> GetCompletedSessionDetailsOutput:
        """完了済 Session から確定額・説明を取得 (line_items expand).

        webhook payload には line_items が含まれないため、別途 retrieve で取得する.

        Raises:
            PaymentSystemError: 一時障害.
            PaymentConfigError: 恒久エラー (session 不存在等).
        """
        try:
            # expand=["line_items"] で line_items を同一レスポンスに含める (追加 API call なし).
            session = stripe.checkout.Session.retrieve(
                session_id, expand=["line_items"],
            )
        except (stripe.RateLimitError, stripe.APIConnectionError, stripe.APIError) as e:
            logger.warning("Stripe transient: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        except (
            stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError,
        ) as e:
            logger.error(
                "Stripe permanent: req=%s type=%s code=%s",
                e.request_id, type(e).__name__, getattr(e, "code", None),
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        except stripe.StripeError as e:
            logger.exception("Stripe unexpected: req=%s type=%s", e.request_id, type(e).__name__)
            raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e

        # expand=["line_items"] 指定したので line_items は必ず返る (Stripe API 仕様).
        # None なら Stripe API が契約を破ってるので恒久エラーとして surface (assert は -O で消えるので使わない).
        if session.line_items is None:
            raise PaymentConfigError(
                "Stripe contract violation: session.line_items is None despite expand",
            )
        # 我々の create_checkout_session は line_items を 1 件しか送らないので [0] 固定で OK.
        line_item = session.line_items.data[0]
        return GetCompletedSessionDetailsOutput(
            amount=line_item.amount_total,
            description=line_item.description or "",
        )

    def construct_webhook_event(
        self, params: ConstructWebhookEventInput,
    ) -> ConstructWebhookEventOutput:
        """Webhook payload を検証して event を返す.

        Raises:
            WebhookSignatureError: 署名検証失敗 / JSON 不正 / thin event.
        """
        try:
            # construct_event は内部で署名検証 → JSON parse → Event 構築を行う.
            # 署名検証失敗 / JSON 不正 / thin event (data が空) のいずれかで例外を投げる.
            event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
                params.payload, params.sig_header, params.secret,
            )
        # 署名検証失敗 = secret が違う or 改竄.
        except stripe.SignatureVerificationError as e:
            raise WebhookSignatureError(f"signature verification failed: {e}") from e
        # JSON 不正 / thin event (data 欠落) は ValueError として上がってくる.
        except ValueError as e:
            raise WebhookSignatureError(f"invalid payload (json or thin event): {e}") from e

        # event.data.object が実際の resource (Session / Charge 等). handler はこれを受ける.
        return ConstructWebhookEventOutput(
            event_id=event["id"],
            event_type=event["type"],
            data=event["data"]["object"],
        )
