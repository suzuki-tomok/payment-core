"""Stripe SDK の wrap. service は ここから import する."""

from typing import cast

from django.apps import apps

from .client import StripeClient
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


def get_stripe_client() -> StripeClient:
    """payment app の AppConfig に保存されている StripeClient を返す.

    apps.py の ready() で USE_MOCK_STRIPE flag に従って実体 / mock を選択済.
    """
    # PaymentConfig.stripe_client は AppConfig の base class には無い属性なので attr-defined は ignore.
    # cast で StripeClient 型を明示し no-any-return を回避.
    return cast(StripeClient, apps.get_app_config("payment").stripe_client)  # type: ignore[attr-defined]


__all__ = [
    "ConstructWebhookEventInput",
    "ConstructWebhookEventOutput",
    "CreateCheckoutSessionInput",
    "CreateCheckoutSessionOutput",
    "CreateCustomerInput",
    "GetCompletedSessionDetailsOutput",
    "PaymentConfigError",
    "PaymentSystemError",
    "StripeClient",
    "WebhookSignatureError",
    "get_stripe_client",
]
