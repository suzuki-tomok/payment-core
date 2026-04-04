from django.conf import settings
from django.db import models

from .company import Company


class CompanyUsageHistory(models.Model):
    class Type(models.TextChoices):
        DOCUMENT = "document", "Document"
        AI_CHAT = "ai_chat", "AI Chat"

    class Source(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        CREDIT = "credit", "Credit"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="usage_histories")
    type = models.CharField(max_length=20, choices=Type.choices)
    source = models.CharField(max_length=20, choices=Source.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_histories")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.type} usage: company={self.company_id} at {self.created_at}"
