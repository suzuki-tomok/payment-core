"""StripeWebhookService のテスト."""

from unittest.mock import MagicMock, patch

import pytest

from payments.models import (
    CheckoutSessionStatus,
    CreditPlan,
    CreditStatus,
    InvoiceStatus,
    StripeCustomer,
    SubscriptionPlan,
    SubscriptionStatus,
)
from payments.services import StripeWebhookService

from .mock_stripe import mock_checkout_session, mock_checkout_session_custom, mock_subscription


@pytest.mark.django_db
class TestHandleCheckoutCompleted:
    """handle_checkout_completed のテスト."""

    def test_subscription_type(self, stripe_customer: StripeCustomer) -> None:
        """type=subscription なら CheckoutSessionStatus を completed にするだけ."""
        checkout = CheckoutSessionStatus.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id="cs_sub123",
            type="subscription",
        )

        StripeWebhookService.handle_checkout_completed({"id": "cs_sub123"})

        checkout.refresh_from_db()
        assert checkout.status == "completed"

    @patch("payments.services.stripe_webhook.stripe.checkout.Session.retrieve")
    def test_credit_type(
        self,
        mock_retrieve: MagicMock,
        stripe_customer: StripeCustomer,
        credit_plan: CreditPlan,
    ) -> None:
        """type=credit なら CheckoutSessionStatus completed + CreditStatus INSERT."""
        CheckoutSessionStatus.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id="cs_credit123",
            type="credit",
        )
        mock_retrieve.return_value = mock_checkout_session("pi_credit123", credit_plan.stripe_price_id)

        StripeWebhookService.handle_checkout_completed({"id": "cs_credit123"})

        credit_status = CreditStatus.objects.get(stripe_payment_id="pi_credit123")
        assert credit_status.credit_plan == credit_plan
        assert credit_status.status == "completed"

    @patch("payments.services.stripe_webhook.stripe.checkout.Session.retrieve")
    def test_custom_type(
        self,
        mock_retrieve: MagicMock,
        stripe_customer: StripeCustomer,
    ) -> None:
        """type=custom なら CheckoutSessionStatus completed + InvoiceStatus INSERT."""
        CheckoutSessionStatus.objects.create(
            stripe_customer=stripe_customer,
            stripe_session_id="cs_custom123",
            type="custom",
        )
        mock_retrieve.return_value = mock_checkout_session_custom("pi_custom123", "コンサル費用", 5000)

        StripeWebhookService.handle_checkout_completed({"id": "cs_custom123"})

        invoice = InvoiceStatus.objects.get(stripe_payment_id="pi_custom123")
        assert invoice.description == "コンサル費用"
        assert invoice.amount == 5000
        assert invoice.status == "completed"

    def test_session_not_found(self) -> None:
        """存在しない session_id なら何もしない."""
        StripeWebhookService.handle_checkout_completed({"id": "cs_nonexistent"})


@pytest.mark.django_db
class TestHandleSubscriptionCreated:
    """handle_subscription_created のテスト."""

    @patch("payments.services.stripe_webhook.stripe.Subscription.retrieve")
    def test_creates_history(
        self,
        mock_retrieve: MagicMock,
        stripe_customer: StripeCustomer,
        subscription_plan: SubscriptionPlan,
    ) -> None:
        """SubscriptionStatus を INSERT."""
        mock_retrieve.return_value = mock_subscription(
            subscription_plan.stripe_price_id, 1743465600, 1746144000,
        )

        StripeWebhookService.handle_subscription_created({
            "customer": stripe_customer.stripe_customer_id,
            "id": "sub_new123",
        })

        history = SubscriptionStatus.objects.get(stripe_subscription_id="sub_new123")
        assert history.status == "created"
        assert history.subscription_plan == subscription_plan


@pytest.mark.django_db
class TestHandleSubscriptionUpdated:
    """handle_subscription_updated のテスト."""

    @patch("payments.services.stripe_webhook.stripe.Subscription.retrieve")
    def test_updates_history(
        self,
        mock_retrieve: MagicMock,
        subscription_status: SubscriptionStatus,
    ) -> None:
        """SubscriptionStatus を UPDATE."""
        mock_retrieve.return_value = mock_subscription("price_test_standard", 1746144000, 1748736000)

        StripeWebhookService.handle_subscription_updated({"id": "sub_test123", "customer": "cus_test123"})

        subscription_status.refresh_from_db()
        assert subscription_status.status == "updated"


@pytest.mark.django_db
class TestHandleSubscriptionDeleted:
    """handle_subscription_deleted のテスト."""

    def test_deletes_history(self, subscription_status: SubscriptionStatus) -> None:
        """SubscriptionStatus.status を deleted に UPDATE."""
        StripeWebhookService.handle_subscription_deleted({"id": "sub_test123", "customer": "cus_test123"})

        subscription_status.refresh_from_db()
        assert subscription_status.status == "deleted"


@pytest.mark.django_db
class TestHandleChargeRefunded:
    """handle_charge_refunded のテスト."""

    def test_refund_credit(self, credit_status: CreditStatus) -> None:
        """CreditStatus.status を refunded に UPDATE."""
        StripeWebhookService.handle_charge_refunded({"payment_intent": "pi_test123", "customer": "cus_test123"})

        credit_status.refresh_from_db()
        assert credit_status.status == "refunded"

    def test_refund_invoice(self, stripe_customer: StripeCustomer) -> None:
        """InvoiceStatus.status を refunded に UPDATE."""
        invoice = InvoiceStatus.objects.create(
            stripe_customer=stripe_customer,
            description="テスト",
            amount=5000,
            stripe_payment_id="pi_invoice123",
            status="completed",
        )

        StripeWebhookService.handle_charge_refunded({"payment_intent": "pi_invoice123", "customer": "cus_test123"})

        invoice.refresh_from_db()
        assert invoice.status == "refunded"

    def test_refund_not_found(self) -> None:
        """該当する History がなくても例外が発生しない."""
        StripeWebhookService.handle_charge_refunded({"payment_intent": "pi_nonexistent", "customer": "cus_test123"})
