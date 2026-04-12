"""StripeCheckoutValidator のテスト."""

import pytest

from payments.models import CreditPlan, SubscriptionHistory, SubscriptionPlan, User
from payments.services import StripeCheckoutValidator


@pytest.mark.django_db
class TestValidateSubscription:
    """validate_subscription のテスト."""

    def test_plan_id_empty(self, user: User) -> None:
        """plan_id が空ならエラー."""
        assert StripeCheckoutValidator.validate_subscription(user, "") == "プランが選択されていません。"

    def test_plan_id_not_found(self, user: User) -> None:
        """存在しない plan_id ならエラー."""
        assert StripeCheckoutValidator.validate_subscription(user, "99999") == "指定されたプランが見つかりません。"

    def test_already_subscribed(
        self, user: User, subscription_plan: SubscriptionPlan, subscription_history: SubscriptionHistory,
    ) -> None:
        """既にサブスク契約中ならエラー."""
        result = StripeCheckoutValidator.validate_subscription(user, str(subscription_plan.id))
        assert result == "既にサブスクリプションを契約中です。"

    def test_deleted_subscription_allows_new(
        self, user: User, subscription_plan: SubscriptionPlan, subscription_history: SubscriptionHistory,
    ) -> None:
        """解約済み（deleted）なら新規契約できる."""
        subscription_history.status = "deleted"
        subscription_history.save()
        assert StripeCheckoutValidator.validate_subscription(user, str(subscription_plan.id)) is None

    def test_valid(self, user: User, subscription_plan: SubscriptionPlan) -> None:
        """正常な plan_id ならエラーなし."""
        assert StripeCheckoutValidator.validate_subscription(user, str(subscription_plan.id)) is None


@pytest.mark.django_db
class TestValidateCredit:
    """validate_credit のテスト."""

    def test_credit_plan_id_empty(self) -> None:
        """credit_plan_id が空ならエラー."""
        assert StripeCheckoutValidator.validate_credit("") == "クレジットプランが選択されていません。"

    def test_credit_plan_id_not_found(self) -> None:
        """存在しない credit_plan_id ならエラー."""
        assert StripeCheckoutValidator.validate_credit("99999") == "指定されたクレジットプランが見つかりません。"

    def test_valid(self, credit_plan: CreditPlan) -> None:
        """正常な credit_plan_id ならエラーなし."""
        assert StripeCheckoutValidator.validate_credit(str(credit_plan.id)) is None


class TestValidateCustom:
    """validate_custom のテスト."""

    def test_amount_not_number(self) -> None:
        """金額が数値でないならエラー."""
        error, _ = StripeCheckoutValidator.validate_custom("abc", "テスト")
        assert error == "金額は数値で入力してください。"

    def test_amount_zero(self) -> None:
        """金額が 0 ならエラー."""
        error, _ = StripeCheckoutValidator.validate_custom("0", "テスト")
        assert error == "金額は1円以上で入力してください。"

    def test_amount_negative(self) -> None:
        """金額がマイナスならエラー."""
        error, _ = StripeCheckoutValidator.validate_custom("-100", "テスト")
        assert error == "金額は1円以上で入力してください。"

    def test_amount_over_limit(self) -> None:
        """金額が上限超えならエラー."""
        error, _ = StripeCheckoutValidator.validate_custom("1000001", "テスト")
        assert error == "金額は1,000,000円以下で入力してください。"

    def test_description_empty(self) -> None:
        """説明が空ならエラー."""
        error, _ = StripeCheckoutValidator.validate_custom("1000", "")
        assert error == "説明を入力してください。"

    def test_description_whitespace_only(self) -> None:
        """説明が空白のみならエラー."""
        error, _ = StripeCheckoutValidator.validate_custom("1000", "   ")
        assert error == "説明を入力してください。"

    def test_valid(self) -> None:
        """正常な入力ならエラーなし."""
        error, amount = StripeCheckoutValidator.validate_custom("5000", "コンサル費用")
        assert error is None
        assert amount == 5000

    def test_valid_max_amount(self) -> None:
        """上限ぴったりならOK."""
        error, amount = StripeCheckoutValidator.validate_custom("1000000", "テスト")
        assert error is None
        assert amount == 1000000
