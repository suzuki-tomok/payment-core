"""payment app の内部実装. consumer は payment.api から import すること.

このパッケージを import した時点で Stripe SDK の global 設定が初期化される.
"""

import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = settings.STRIPE_API_VERSION

from .stripe_webhook_handlers import StripeWebhookHandlers  # noqa: E402  Stripe 設定後に import

__all__ = ["StripeWebhookHandlers"]
