"""payment app の AppConfig.

ready() で StripeClient を 1 回だけ初期化し、`self.stripe_client` に保持する.
view / service は `payment.stripe.get_stripe_client()` 経由で取り出して使う.
"""

from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from payment.stripe.client import StripeClient


class PaymentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payment"

    # ready() で代入される. mock も StripeClient を継承してるので型は同じで良い.
    stripe_client: StripeClient

    def ready(self) -> None:
        """Django 起動時に呼ばれる. StripeClient を構築して self に保存."""
        use_mock = getattr(settings, "USE_MOCK_STRIPE", False)

        # 安全網: 本番 (DEBUG=False) で誤って mock を有効にすると無音で in-memory 動作してしまう.
        # 起動時に明示エラーで止める.
        if use_mock and not settings.DEBUG:
            raise ImproperlyConfigured(
                "USE_MOCK_STRIPE=True is not allowed when DEBUG=False (production safety)",
            )

        if use_mock:
            # stripe-cli が使えない開発者向け. Stripe API は叩かず in-memory で動作.
            from payment.stripe.client_mock import StripeClientMock
            self.stripe_client = StripeClientMock()
        else:
            self.stripe_client = StripeClient(
                api_key=settings.STRIPE_SECRET_KEY,
                api_version=settings.STRIPE_API_VERSION,
            )
