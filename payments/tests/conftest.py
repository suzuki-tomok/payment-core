"""テスト用 fixture."""

from datetime import UTC, datetime

import pytest

from payments.models import (
    Company,
    CreditHistory,
    CreditPlan,
    StripeCustomer,
    SubscriptionHistory,
    SubscriptionPlan,
    User,
)


@pytest.fixture
def company() -> Company:
    """テスト用 Company."""
    return Company.objects.create(name="テスト株式会社")


@pytest.fixture
def user(company: Company) -> User:
    """テスト用 User."""
    return User.objects.create_user(username="testuser", password="test1234", company=company)  # noqa: S106


@pytest.fixture
def stripe_customer(company: Company) -> StripeCustomer:
    """テスト用 StripeCustomer."""
    return StripeCustomer.objects.create(company=company, stripe_customer_id="cus_test123")


@pytest.fixture
def subscription_plan() -> SubscriptionPlan:
    """テスト用 SubscriptionPlan."""
    return SubscriptionPlan.objects.create(
        name="Standard",
        stripe_price_id="price_test_standard",
        monthly_document_limit=100,
        monthly_ai_chat_limit=50,
    )


@pytest.fixture
def subscription_history(
    stripe_customer: StripeCustomer,
    subscription_plan: SubscriptionPlan,
) -> SubscriptionHistory:
    """テスト用 SubscriptionHistory (status=created)."""
    return SubscriptionHistory.objects.create(
        stripe_customer=stripe_customer,
        subscription_plan=subscription_plan,
        stripe_subscription_id="sub_test123",
        status="created",
        current_period_start=datetime(2026, 4, 1, tzinfo=UTC),
        current_period_end=datetime(2026, 5, 1, tzinfo=UTC),
    )


@pytest.fixture
def credit_plan() -> CreditPlan:
    """テスト用 CreditPlan."""
    return CreditPlan.objects.create(
        name="クレジット10パック",
        stripe_price_id="price_test_credit_10",
        document_credits=10,
        ai_chat_credits=10,
    )


@pytest.fixture
def credit_history(
    stripe_customer: StripeCustomer,
    credit_plan: CreditPlan,
) -> CreditHistory:
    """テスト用 CreditHistory (status=completed)."""
    return CreditHistory.objects.create(
        stripe_customer=stripe_customer,
        credit_plan=credit_plan,
        stripe_payment_id="pi_test123",
        status="completed",
    )
