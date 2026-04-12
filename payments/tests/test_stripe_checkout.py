"""StripeCheckoutService のテスト."""

from unittest.mock import MagicMock, patch

import pytest

from payments.models import CheckoutSession, Company, CreditPlan, StripeCustomer, SubscriptionPlan
from payments.services import StripeCheckoutService


@pytest.mark.django_db
class TestGetOrCreateCustomer:
    """get_or_create_customer のテスト."""

    def test_existing_customer(self, company: Company, stripe_customer: StripeCustomer) -> None:
        """既に StripeCustomer があればそれを返す."""
        result = StripeCheckoutService.get_or_create_customer(company)
        assert result.id == stripe_customer.id
        assert result.stripe_customer_id == "cus_test123"

    @patch("payments.services.stripe_checkout.stripe.Customer.create")
    def test_new_customer(self, mock_create: MagicMock, company: Company) -> None:
        """StripeCustomer がなければ Stripe に作成して DB に保存."""
        mock_create.return_value = MagicMock(id="cus_new123")

        result = StripeCheckoutService.get_or_create_customer(company)

        mock_create.assert_called_once_with(name=company.name)
        assert result.stripe_customer_id == "cus_new123"
        assert result.company == company
        assert StripeCustomer.objects.count() == 1


@pytest.mark.django_db
class TestCreateSubscriptionCheckout:
    """create_subscription_checkout のテスト."""

    @patch("payments.services.stripe_checkout.stripe.checkout.Session.create")
    def test_creates_session_and_db_record(
        self,
        mock_create: MagicMock,
        stripe_customer: StripeCustomer,
        subscription_plan: SubscriptionPlan,
    ) -> None:
        """Stripe Session を作成し、CheckoutSession を DB に保存."""
        mock_create.return_value = MagicMock(id="cs_test123", url="https://checkout.stripe.com/xxx")

        session = StripeCheckoutService.create_subscription_checkout(
            stripe_customer, subscription_plan, "http://localhost:8000/",
        )

        assert session.id == "cs_test123"
        mock_create.assert_called_once()

        # DB に CheckoutSession が作られたか
        checkout = CheckoutSession.objects.get(stripe_session_id="cs_test123")
        assert checkout.type == "subscription"
        assert checkout.status == "pending"
        assert checkout.stripe_customer == stripe_customer


@pytest.mark.django_db
class TestCreateCreditCheckout:
    """create_credit_checkout のテスト."""

    @patch("payments.services.stripe_checkout.stripe.checkout.Session.create")
    def test_creates_session_and_db_record(
        self,
        mock_create: MagicMock,
        stripe_customer: StripeCustomer,
        credit_plan: CreditPlan,
    ) -> None:
        """Stripe Session を作成し、CheckoutSession を DB に保存."""
        mock_create.return_value = MagicMock(id="cs_credit123", url="https://checkout.stripe.com/xxx")

        session = StripeCheckoutService.create_credit_checkout(
            stripe_customer, credit_plan, "http://localhost:8000/",
        )

        assert session.id == "cs_credit123"
        mock_create.assert_called_once()

        checkout = CheckoutSession.objects.get(stripe_session_id="cs_credit123")
        assert checkout.type == "credit"
        assert checkout.status == "pending"


@pytest.mark.django_db
class TestCreateCustomCheckout:
    """create_custom_checkout のテスト."""

    @patch("payments.services.stripe_checkout.stripe.checkout.Session.create")
    def test_creates_session_and_db_record(
        self,
        mock_create: MagicMock,
        stripe_customer: StripeCustomer,
    ) -> None:
        """動的金額で Stripe Session を作成し、CheckoutSession を DB に保存."""
        mock_create.return_value = MagicMock(id="cs_custom123", url="https://checkout.stripe.com/xxx")

        session = StripeCheckoutService.create_custom_checkout(
            stripe_customer, 5000, "コンサル費用", "http://localhost:8000/",
        )

        assert session.id == "cs_custom123"

        # price_data が渡されたか確認
        call_kwargs = mock_create.call_args[1]
        line_item = call_kwargs["line_items"][0]
        assert line_item["price_data"]["unit_amount"] == 5000
        assert line_item["price_data"]["product_data"]["name"] == "コンサル費用"

        checkout = CheckoutSession.objects.get(stripe_session_id="cs_custom123")
        assert checkout.type == "custom"
        assert checkout.status == "pending"
