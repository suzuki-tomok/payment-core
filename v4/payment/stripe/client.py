"""StripeClient: Stripe SDK の薄いラッパー (gateway).

役割:
    - Stripe SDK の例外を 3 種類 (PaymentSystemError / PaymentConfigError /
      WebhookSignatureError) に翻訳して service 側に出す
    - service 側に必要なフィールドだけ DTO で返す (stripe.* オブジェクトを leak させない)
    - api_key / api_version の保持 (instance ごと)

service は stripe.* を直接 import せず、StripeClient のメソッドを呼ぶ.
テストでは Mock(spec=StripeClient) で差し替え可能.

ログ方針:
    - 全 except 節で extra={"stripe_request_id": ..., "stripe_error_type": ...} の構造化形式.
      log aggregation 側で req_id / error type 別に集計しやすくする.
"""

import json
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
            logger.warning(
                "Stripe transient",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        # 恒久エラー (リトライしても直らない. 開発者対応必要):
        #   AuthenticationError  = API key 無効
        #   InvalidRequestError  = リクエスト不正 (パラメータ間違い等)
        #   IdempotencyError     = 同じ idempotency_key で異なるパラメータ送信
        except (
            stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError,
        ) as e:
            logger.error(
                "Stripe permanent",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                    "stripe_error_code": getattr(e, "code", None),
                },
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        # 上記以外の StripeError. 想定外なので一時障害扱いにフォールバック (logger.exception で stacktrace)
        except stripe.StripeError as e:
            logger.exception(
                "Stripe unexpected",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
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
                # metadata は webhook で逆引きするため必須 (order_id 等を入れる).
                metadata=params.metadata,
            )
        except (stripe.RateLimitError, stripe.APIConnectionError, stripe.APIError) as e:
            logger.warning(
                "Stripe transient",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        except (
            stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError,
        ) as e:
            logger.error(
                "Stripe permanent",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                    "stripe_error_code": getattr(e, "code", None),
                },
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        except stripe.StripeError as e:
            logger.exception(
                "Stripe unexpected",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
            raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e

        # mode=payment かつ Session.create 直後は url が必ず set される (Stripe API 仕様).
        # None なら Stripe API が契約を破ってるので恒久エラーとして surface (assert は -O で消えるので使わない).
        if session.url is None:
            raise PaymentConfigError("Stripe contract violation: session.url is None after create")
        # payment_intent_id は ここでは取得しない:
        # Stripe Adaptive Pricing 等 lazy PI 設定が有効な account では、Session.create 時点で
        # PaymentIntent が作られず response.payment_intent=null となる.
        # 確定値は webhook (checkout.session.completed) で Session.retrieve 後に取得する (v1 と同じパターン).
        return CreateCheckoutSessionOutput(
            session_id=session.id,
            url=session.url,
        )

    def get_completed_session_details(
        self, session_id: str,
    ) -> GetCompletedSessionDetailsOutput:
        """完了済 Session から確定額・説明・payment_intent_id を取得 (line_items expand).

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
            logger.warning(
                "Stripe transient",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
            raise PaymentSystemError(f"Stripe transient error (req={e.request_id})") from e
        except (
            stripe.AuthenticationError, stripe.InvalidRequestError, stripe.IdempotencyError,
        ) as e:
            logger.error(
                "Stripe permanent",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                    "stripe_error_code": getattr(e, "code", None),
                },
            )
            raise PaymentConfigError(f"Stripe permanent error (req={e.request_id})") from e
        except stripe.StripeError as e:
            logger.exception(
                "Stripe unexpected",
                extra={
                    "stripe_request_id": e.request_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
            raise PaymentSystemError(f"Unexpected Stripe error (req={e.request_id})") from e

        # expand=["line_items"] 指定したので line_items は必ず返る (Stripe API 仕様).
        # None なら Stripe API が契約を破ってるので恒久エラーとして surface (assert は -O で消えるので使わない).
        if session.line_items is None:
            raise PaymentConfigError(
                "Stripe contract violation: session.line_items is None despite expand",
            )
        # 我々の create_checkout_session は line_items を 1 件しか送らないので [0] 固定で OK.
        line_item = session.line_items.data[0]
        # webhook 時点 (= 顧客が決済完了した後) は payment_intent が確定して str ID で返る.
        # Adaptive Pricing 等で lazy だった PI もこの時点で作られている.
        payment_intent_id = str(session.payment_intent)
        return GetCompletedSessionDetailsOutput(
            amount=line_item.amount_total,
            description=line_item.description or "",
            payment_intent_id=payment_intent_id,
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
            # 戻り値の StripeObject は __getattr__ の都合で dict メソッド (.get 等) を遮るため
            # ここでは捨てる. データ抽出は raw payload を素の json.loads で行う (下記).
            stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
                params.payload, params.sig_header, params.secret,
            )
        # 署名検証失敗 = secret が違う or 改竄.
        except stripe.SignatureVerificationError as e:
            raise WebhookSignatureError(f"signature verification failed: {e}") from e
        # JSON 不正 / thin event (data 欠落) は ValueError として上がってくる.
        except ValueError as e:
            raise WebhookSignatureError(f"invalid payload (json or thin event): {e}") from e

        # 検証成功後は raw payload を素の dict として parse.
        # SDK の StripeObject に依存せず、mock (json.loads 結果) と完全に型整合する.
        # event.data.object が実際の resource (Session / Charge 等). handler はこれを受ける.
        event_dict = json.loads(params.payload)
        return ConstructWebhookEventOutput(
            event_id=event_dict["id"],
            event_type=event_dict["type"],
            data=event_dict["data"]["object"],
        )
