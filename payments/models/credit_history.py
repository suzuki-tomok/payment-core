from django.db import models

from .credit_plan import CreditPlan
from .stripe_customer import StripeCustomer


class CreditHistory(models.Model):
    stripe_customer = models.ForeignKey(StripeCustomer, on_delete=models.CASCADE, related_name="credit_histories")
    credit_plan = models.ForeignKey(CreditPlan, on_delete=models.PROTECT, related_name="credit_histories")
    stripe_payment_id = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.credit_plan.name} at {self.created_at}"
