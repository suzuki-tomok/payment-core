from dataclasses import dataclass

from ..models import (
    Company,
    CompanyUsageHistory,
    CreditHistory,
)


@dataclass
class RemainingCreditDto:
    """クレジット残量."""

    document_remaining: int
    ai_chat_remaining: int


class RemainingCreditService:
    """クレジット残量の計算."""

    @staticmethod
    def get_remaining(company: Company) -> RemainingCreditDto:
        """クレジットの残量を取得."""

        # 有効な（is_active=True）購入履歴から合計クレジット数を算出
        credit_histories = CreditHistory.objects.filter(
            stripe_customer__company=company,
            is_active=True,
        ).select_related("credit_plan")

        total_document = 0
        total_ai_chat = 0
        for ch in credit_histories:
            total_document += ch.credit_plan.document_credits
            total_ai_chat += ch.credit_plan.ai_chat_credits

        # クレジットから消費されたドキュメント数
        doc_used = CompanyUsageHistory.objects.filter(
            company=company,
            type="document",
            source="credit",
        ).count()

        # クレジットから消費されたAIチャット数
        ai_used = CompanyUsageHistory.objects.filter(
            company=company,
            type="ai_chat",
            source="credit",
        ).count()

        # 購入合計 - 消費数 = 残量
        return RemainingCreditDto(
            document_remaining=max(0, total_document - doc_used),
            ai_chat_remaining=max(0, total_ai_chat - ai_used),
        )
