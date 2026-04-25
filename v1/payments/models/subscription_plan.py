from django.db import models


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=255)
    stripe_price_id = models.CharField(max_length=255, unique=True)
    monthly_document_limit = models.IntegerField()
    monthly_ai_chat_limit = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name
