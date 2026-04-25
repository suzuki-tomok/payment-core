from django.db import models


class StripeCustomer(models.Model):
    """外部システムの会社 (company_id) と Stripe Customer の紐付け."""

    company_id = models.CharField(max_length=255, unique=True)
    company_name = models.CharField(max_length=255)
    stripe_customer_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.company_name} ({self.company_id})"
