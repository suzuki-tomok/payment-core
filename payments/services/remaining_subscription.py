from dataclasses import dataclass

from ..models import (
    Company,
    CompanyUsageHistory,
    SubscriptionHistory,
)


@dataclass
class RemainingSubscriptionDto:
    """サブスクリプション残量."""

    plan_name: str
    document_limit: int
    document_remaining: int
    ai_chat_limit: int
    ai_chat_remaining: int


class RemainingSubscriptionService:
    """サブスクリプション残量の計算."""

    @staticmethod
    def get_remaining(company: Company) -> RemainingSubscriptionDto:
        """サブスクリプションの残量を取得."""

        # 最新のサブスクリプション履歴を取得し、有効かどうか判定
        subscription = (
            SubscriptionHistory.objects.filter(
                stripe_customer__company=company,
            )
            .select_related("subscription_plan")
            .order_by("-created_at")
            .first()
        )

        # 最新レコードが active/trialing でなければ未契約扱い
        if subscription and subscription.status not in ("active", "trialing"):
            subscription = None

        # サブスク未契約の場合
        if not subscription:
            return RemainingSubscriptionDto(
                plan_name="未契約",
                document_limit=0,
                document_remaining=0,
                ai_chat_limit=0,
                ai_chat_remaining=0,
            )

        plan = subscription.subscription_plan
        period_start = subscription.current_period_start
        period_end = subscription.current_period_end

        # 現在のサブスク期間内のドキュメント使用数
        doc_used = CompanyUsageHistory.objects.filter(
            company=company,
            type="document",
            source="subscription",
            created_at__gte=period_start,
            created_at__lt=period_end,
        ).count()

        # 現在のサブスク期間内のAIチャット使用数
        ai_used = CompanyUsageHistory.objects.filter(
            company=company,
            type="ai_chat",
            source="subscription",
            created_at__gte=period_start,
            created_at__lt=period_end,
        ).count()

        # 月間上限 - 使用数 = 残量
        return RemainingSubscriptionDto(
            plan_name=plan.name,
            document_limit=plan.monthly_document_limit,
            document_remaining=max(0, plan.monthly_document_limit - doc_used),
            ai_chat_limit=plan.monthly_ai_chat_limit,
            ai_chat_remaining=max(0, plan.monthly_ai_chat_limit - ai_used),
        )
