"""payment app の DB モデル.

設計方針:
    - Payment は「決済成功した事実」のみを記録する (pending / canceled / expired は持たない).
    - 起票時 (Session.create 時) には Payment を作らない. webhook 受信時に初めて作成する.
    - 状態は2値: 通常 (succeeded) / 返金済 (is_refunded=True).
    - Stripe Session の状態管理 (open / expired) は Stripe 側に任せる (DB ミラーしない).
"""

from django.db import models


class StripeCustomer(models.Model):
    """外部システムの会社 (company_id) と Stripe Customer の紐付け."""

    company_id = models.CharField(max_length=255, unique=True)
    company_name = models.CharField(max_length=255)
    stripe_customer_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.company_name} ({self.company_id})"


class Payment(models.Model):
    """Stripe Checkout の決済成功記録.

    作成タイミング: webhook (checkout.session.completed) 受信時のみ.
    既に同 order_id の Payment が存在すれば無視 (1 order = 1 successful Payment).
    """

    stripe_customer = models.ForeignKey(
        StripeCustomer, on_delete=models.PROTECT, related_name="payments",
    )
    order_id = models.CharField(max_length=255, unique=True)
    stripe_session_id = models.CharField(max_length=255, unique=True)
    stripe_payment_id = models.CharField(max_length=255, unique=True)
    amount = models.IntegerField()
    description = models.CharField(max_length=255)
    is_refunded = models.BooleanField(default=False)
    refunded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        suffix = " (refunded)" if self.is_refunded else ""
        return f"{self.order_id}{suffix}"


class StripeWebhookEventLog(models.Model):
    """Stripe webhook 受信の冪等性担保. event_id の unique 制約で重複処理を防ぐ."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.event_type}: {self.event_id}"
