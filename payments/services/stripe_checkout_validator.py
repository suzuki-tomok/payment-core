from ..models import (
    CreditPlan,
    SubscriptionHistory,
    SubscriptionPlan,
    User,
)

# カスタム支払いの上限金額（円）
CUSTOM_AMOUNT_MAX = 1_000_000


class StripeCheckoutValidator:
    """Checkout のバリデーション."""

    @staticmethod
    def validate_subscription(user: User, plan_id: str) -> str | None:
        """サブスク Checkout のバリデーション. エラーメッセージを返す. None なら OK."""
        if not plan_id:
            return "プランが選択されていません。"

        if not SubscriptionPlan.objects.filter(id=plan_id).exists():
            return "指定されたプランが見つかりません。"

        # 二重契約防止
        has_active = SubscriptionHistory.objects.filter(
            stripe_customer__company=user.company,
            status__in=["created", "updated"],
        ).exists()
        if has_active:
            return "既にサブスクリプションを契約中です。"

        return None

    @staticmethod
    def validate_credit(credit_plan_id: str) -> str | None:
        """クレジット Checkout のバリデーション. エラーメッセージを返す. None なら OK."""
        if not credit_plan_id:
            return "クレジットプランが選択されていません。"

        if not CreditPlan.objects.filter(id=credit_plan_id).exists():
            return "指定されたクレジットプランが見つかりません。"

        return None

    @staticmethod
    def validate_custom(amount_str: str, description: str) -> tuple[str | None, int]:
        """カスタム Checkout のバリデーション. (エラーメッセージ, amount) を返す."""
        try:
            amount = int(amount_str)
        except ValueError:
            return "金額は数値で入力してください。", 0

        if amount <= 0:
            return "金額は1円以上で入力してください。", 0

        if amount > CUSTOM_AMOUNT_MAX:
            return f"金額は{CUSTOM_AMOUNT_MAX:,}円以下で入力してください。", 0

        if not description.strip():
            return "説明を入力してください。", 0

        return None, amount
