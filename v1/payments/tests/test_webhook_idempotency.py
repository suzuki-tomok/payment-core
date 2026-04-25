"""Webhook 冪等性のテスト."""

import pytest
from django.db import IntegrityError

from payments.models import StripeCustomer, WebhookEventLog


@pytest.mark.django_db
class TestWebhookIdempotency:
    """WebhookEventLog による冪等性管理のテスト."""

    def test_duplicate_event_rejected(self, stripe_customer: StripeCustomer) -> None:
        """同じ event_id は2回作成できない（unique制約）."""
        WebhookEventLog.objects.create(
            event_id="evt_dup",
            event_type="checkout.session.completed",
            stripe_customer_id=stripe_customer.stripe_customer_id,
        )
        with pytest.raises(IntegrityError):
            WebhookEventLog.objects.create(
                event_id="evt_dup",
                event_type="checkout.session.completed",
                stripe_customer_id=stripe_customer.stripe_customer_id,
            )
