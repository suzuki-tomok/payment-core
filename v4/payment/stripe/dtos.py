"""StripeClient の入出力 DTO. service と client の間の契約.

stripe.* の型を service に leak させないため、複数フィールドの入出力は DTO で固定する.
1 フィールドだけのものは primitive のまま (DTO ラップしない).
命名は <MethodName>Input / <MethodName>Output で対称.
"""

from dataclasses import dataclass
from typing import Any

# =============================================================================
# Input DTOs (service → client)
# =============================================================================


@dataclass(frozen=True)
class CreateCustomerInput:
    """create_customer の入力."""

    name: str
    idempotency_key: str


@dataclass(frozen=True)
class CreateCheckoutSessionInput:
    """create_checkout_session の入力. mode=payment / JPY 固定なので通貨は持たない.

    metadata は Session に紐付く任意の key-value. webhook 受信時に
    event.data.object.metadata で取得できるため、order_id 等の逆引きキーを入れる.
    """

    customer_id: str
    amount: int
    description: str
    success_url: str
    cancel_url: str
    idempotency_key: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class ConstructWebhookEventInput:
    """construct_webhook_event の入力."""

    payload: bytes
    sig_header: str
    secret: str


# =============================================================================
# Output DTOs (client → service)
# =============================================================================


@dataclass(frozen=True)
class CreateCheckoutSessionOutput:
    """create_checkout_session の戻り値.

    payment_intent_id は持たない: Adaptive Pricing 等で Stripe が PI を lazy 作成するため、
    確定値は webhook (checkout.session.completed) で Session.retrieve 後に取得する.
    """

    session_id: str
    url: str


@dataclass(frozen=True)
class GetCompletedSessionDetailsOutput:
    """完了済 Session から取得した確定値. webhook (checkout.session.completed) で参照する."""

    amount: int
    description: str
    payment_intent_id: str


@dataclass(frozen=True)
class ConstructWebhookEventOutput:
    """検証済 webhook event の必要フィールド."""

    event_id: str
    event_type: str
    data: dict[str, Any]
