from django.db import models

from .credit_plan import CreditPlan
from .stripe_customer import StripeCustomer


class CreditStatus(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        REFUNDED = "refunded", "Refunded"

    stripe_customer = models.ForeignKey(StripeCustomer, on_delete=models.CASCADE, related_name="credit_statuses")
    credit_plan = models.ForeignKey(CreditPlan, on_delete=models.PROTECT, related_name="credit_statuses")
    stripe_payment_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCEEDED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "credit statuses"

    def __str__(self) -> str:
        return f"{self.credit_plan.name} ({self.status}) at {self.created_at}"
