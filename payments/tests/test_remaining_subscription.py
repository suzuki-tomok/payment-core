"""RemainingSubscriptionService のテスト."""

import pytest

from payments.models import Company, CompanyUsageHistory, SubscriptionHistory, User
from payments.services.remaining_subscription import RemainingSubscriptionService


@pytest.mark.django_db
class TestGetRemaining:
    """get_remaining のテスト."""

    def test_no_subscription(self, company: Company) -> None:
        """サブスク未契約なら全部 0."""
        result = RemainingSubscriptionService.get_remaining(company)

        assert result.plan_name == "未契約"
        assert result.document_limit == 0
        assert result.document_remaining == 0
        assert result.ai_chat_limit == 0
        assert result.ai_chat_remaining == 0

    def test_active_no_usage(
        self, company: Company, subscription_history: SubscriptionHistory,
    ) -> None:
        """サブスク契約中、使用量 0 なら limit = remaining."""
        result = RemainingSubscriptionService.get_remaining(company)

        assert result.plan_name == "Standard"
        assert result.document_limit == 100
        assert result.document_remaining == 100
        assert result.ai_chat_limit == 50
        assert result.ai_chat_remaining == 50

    def test_active_with_usage(
        self, company: Company, user: User, subscription_history: SubscriptionHistory,
    ) -> None:
        """サブスク契約中、一部使用済みなら remaining = limit - used."""
        for _ in range(3):
            CompanyUsageHistory.objects.create(
                company=company, user=user, type="document", source="subscription",
            )
        for _ in range(2):
            CompanyUsageHistory.objects.create(
                company=company, user=user, type="ai_chat", source="subscription",
            )

        result = RemainingSubscriptionService.get_remaining(company)

        assert result.document_remaining == 97
        assert result.ai_chat_remaining == 48

    def test_updated_status(
        self, company: Company, subscription_history: SubscriptionHistory,
    ) -> None:
        """updated ステータスでも有効として扱う."""
        subscription_history.status = "updated"
        subscription_history.save()

        result = RemainingSubscriptionService.get_remaining(company)

        assert result.plan_name == "Standard"
        assert result.document_remaining == 100

    def test_deleted_status(
        self, company: Company, subscription_history: SubscriptionHistory,
    ) -> None:
        """deleted ステータスなら全部 0."""
        subscription_history.status = "deleted"
        subscription_history.save()

        result = RemainingSubscriptionService.get_remaining(company)

        assert result.plan_name == "未契約"
        assert result.document_remaining == 0

    def test_credit_usage_not_counted(
        self, company: Company, user: User, subscription_history: SubscriptionHistory,
    ) -> None:
        """source=credit の使用量はサブスク残量に影響しない."""
        CompanyUsageHistory.objects.create(
            company=company, user=user, type="document", source="credit",
        )

        result = RemainingSubscriptionService.get_remaining(company)

        assert result.document_remaining == 100
