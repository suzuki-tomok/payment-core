"""Stripe SDK の共通設定を集約する. このモジュールを import することで api_key / api_version が初期化される."""

import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = settings.STRIPE_API_VERSION

__all__ = ["stripe"]
