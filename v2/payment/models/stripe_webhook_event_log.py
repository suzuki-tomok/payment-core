from django.db import models


class StripeWebhookEventLog(models.Model):
    """Stripe webhook 受信の冪等性担保. event_id の unique 制約で重複処理を防ぐ."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.event_type}: {self.event_id}"
