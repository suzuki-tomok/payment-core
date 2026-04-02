from django.db import models


class CreditPlan(models.Model):
    name = models.CharField(max_length=255)
    stripe_price_id = models.CharField(max_length=255, unique=True)
    document_credits = models.IntegerField()
    ai_chat_credits = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name
