"""StripeClient のモック実装. local 開発で Stripe API を叩かずに動かすため.

stripe-cli が使えない開発者向けの fake. 本物と同じインターフェースで動作する.

仕組み:
    - 偽 ID 生成 (cus_mock_*, cs_mock_*, pi_mock_*)
    - in-memory dict で session 状態を保持 (プロセス再起動で消える)
    - construct_webhook_event は署名検証をスキップして JSON parse のみ
    - create_checkout_session の URL は local の疑似 Checkout 中継ページを指す.
      その view (mock_checkout_view) が踏まれた時に webhook handler を発火 →
      success_url にリダイレクトする (本物 Stripe の webhook 経路を local 再現).
"""

import json
import logging
import uuid
from typing import Any
from urllib.parse import urlparse

from .client import StripeClient
from .dtos import (
    ConstructWebhookEventInput,
    ConstructWebhookEventOutput,
    CreateCheckoutSessionInput,
    CreateCheckoutSessionOutput,
    CreateCustomerInput,
    GetCompletedSessionDetailsOutput,
)
from .exceptions import PaymentConfigError, WebhookSignatureError

logger = logging.getLogger(__name__)


class StripeClientMock(StripeClient):
    """StripeClient の互換モック. stripe.* を叩かず in-memory で動作.

    StripeClient を継承するが super().__init__() を呼ばない (グローバル stripe.api_key を汚染しない).
    型としては StripeClient なので DI 先で型を変えなくて良い.
    """

    def __init__(self) -> None:
        # super().__init__() を呼ばない. stripe-python の global state をいじらない.
        # session_id → {amount, description, payment_intent_id, success_url, cancel_url}.
        self._sessions: dict[str, dict[str, Any]] = {}
        logger.info("StripeClientMock initialized (no real Stripe API calls)")

    def create_customer(self, params: CreateCustomerInput) -> str:
        """Stripe Customer の代わりに偽 customer_id を返す. 例外は発生させない."""
        customer_id = f"cus_mock_{uuid.uuid4().hex[:14]}"
        logger.info("Mock customer created: id=%s name=%s", customer_id, params.name)
        return customer_id

    def create_checkout_session(
        self, params: CreateCheckoutSessionInput,
    ) -> CreateCheckoutSessionOutput:
        """偽の Checkout Session を作成. URL は local の疑似 Checkout ページを指す.

        session_id / amount / description 等を in-memory に記録し、
        後の get_completed_session_details で復元できるようにする.
        """
        session_id = f"cs_mock_{uuid.uuid4().hex[:14]}"
        payment_intent_id = f"pi_mock_{uuid.uuid4().hex[:14]}"
        # session 状態を in-memory に保存. get_completed_session_details で参照する.
        self._sessions[session_id] = {
            "amount": params.amount,
            "description": params.description,
            "payment_intent_id": payment_intent_id,
            "success_url": params.success_url,
            "cancel_url": params.cancel_url,
        }
        # local の疑似 Checkout URL. 実 view (mock_checkout_view) は USE_MOCK_STRIPE=True
        # の時だけ動き、踏んだ瞬間に webhook handler を発火 → success_url に redirect する.
        # host 部分は success_url から抽出 (caller が build_absolute_uri で組み立て済の絶対 URL).
        parsed = urlparse(params.success_url)
        url = f"{parsed.scheme}://{parsed.netloc}/payment/mock/checkout/{session_id}/"
        logger.info("Mock session created: id=%s url=%s", session_id, url)
        return CreateCheckoutSessionOutput(
            session_id=session_id,
            payment_intent_id=payment_intent_id,
            url=url,
        )

    def get_completed_session_details(
        self, session_id: str,
    ) -> GetCompletedSessionDetailsOutput:
        """in-memory から amount / description を復元."""
        session = self._sessions.get(session_id)
        if session is None:
            # 本物の StripeClient なら無効 session_id で PaymentConfigError を raise する.
            # 挙動を合わせるため mock も同じ例外を投げる.
            raise PaymentConfigError(f"Mock session not found: {session_id}")
        return GetCompletedSessionDetailsOutput(
            amount=session["amount"],
            description=session["description"],
        )

    def construct_webhook_event(
        self, params: ConstructWebhookEventInput,
    ) -> ConstructWebhookEventOutput:
        """署名検証スキップ. JSON parse のみ行う.

        疑似 Checkout ページから自前で構築した event payload を受け取る用途.
        """
        try:
            event = json.loads(params.payload)
        except json.JSONDecodeError as e:
            raise WebhookSignatureError(f"Mock: invalid JSON payload: {e}") from e
        return ConstructWebhookEventOutput(
            event_id=event["id"],
            event_type=event["type"],
            data=event["data"]["object"],
        )
