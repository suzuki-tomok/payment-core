"""RemainingCreditService のテスト."""

import pytest

from payments.models import Company, CompanyUsageHistory, CreditHistory, CreditPlan, StripeCustomer, User
from payments.services.remaining_credit import RemainingCreditService


@pytest.mark.django_db
class TestGetRemaining:
    """get_remaining のテスト."""

    def test_no_credit(self, company: Company) -> None:
        """クレジット購入なしなら全部 0."""
        result = RemainingCreditService.get_remaining(company)

        assert result.document_remaining == 0
        assert result.ai_chat_remaining == 0

    def test_credit_no_usage(
        self, company: Company, credit_history: CreditHistory,
    ) -> None:
        """クレジット購入あり、使用量 0 なら remaining = 購入合計."""
        result = RemainingCreditService.get_remaining(company)

        assert result.document_remaining == 10
        assert result.ai_chat_remaining == 10

    def test_credit_with_usage(
        self, company: Company, user: User, credit_history: CreditHistory,
    ) -> None:
        """クレジット購入あり、一部使用済みなら remaining = 購入合計 - used."""
        for _ in range(3):
            CompanyUsageHistory.objects.create(
                company=company, user=user, type="document", source="credit",
            )
        CompanyUsageHistory.objects.create(
            company=company, user=user, type="ai_chat", source="credit",
        )

        result = RemainingCreditService.get_remaining(company)

        assert result.document_remaining == 7
        assert result.ai_chat_remaining == 9

    def test_multiple_purchases(
        self, company: Company, user: User, stripe_customer: StripeCustomer, credit_plan: CreditPlan,
    ) -> None:
        """複数回購入した場合、合計から使用量を引く."""
        CreditHistory.objects.create(
            stripe_customer=stripe_customer, credit_plan=credit_plan,
            stripe_payment_id="pi_1", status="completed",
        )
        CreditHistory.objects.create(
            stripe_customer=stripe_customer, credit_plan=credit_plan,
            stripe_payment_id="pi_2", status="completed",
        )

        for _ in range(5):
            CompanyUsageHistory.objects.create(
                company=company, user=user, type="document", source="credit",
            )

        result = RemainingCreditService.get_remaining(company)

        # 10 + 10 - 5 = 15
        assert result.document_remaining == 15
        # 10 + 10 - 0 = 20
        assert result.ai_chat_remaining == 20

    def test_refunded_not_counted(
        self, company: Company, stripe_customer: StripeCustomer, credit_plan: CreditPlan,
    ) -> None:
        """refunded のクレジットは残量に含まない."""
        CreditHistory.objects.create(
            stripe_customer=stripe_customer, credit_plan=credit_plan,
            stripe_payment_id="pi_1", status="completed",
        )
        CreditHistory.objects.create(
            stripe_customer=stripe_customer, credit_plan=credit_plan,
            stripe_payment_id="pi_2", status="refunded",
        )

        result = RemainingCreditService.get_remaining(company)

        assert result.document_remaining == 10
        assert result.ai_chat_remaining == 10

    def test_subscription_usage_not_counted(
        self, company: Company, user: User, credit_history: CreditHistory,
    ) -> None:
        """source=subscription の使用量はクレジット残量に影響しない."""
        CompanyUsageHistory.objects.create(
            company=company, user=user, type="document", source="subscription",
        )

        result = RemainingCreditService.get_remaining(company)

        assert result.document_remaining == 10
