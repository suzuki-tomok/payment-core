from django.db import models

from .stripe_customer import StripeCustomer
from .subscription_plan import SubscriptionPlan


class SubscriptionHistory(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIALING = "trialing", "Trialing"
        PAST_DUE = "past_due", "Past Due"
        CANCELED = "canceled", "Canceled"
        UNPAID = "unpaid", "Unpaid"

    stripe_customer = models.ForeignKey(StripeCustomer, on_delete=models.CASCADE, related_name="subscription_histories")
    subscription_plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscription_histories")
    stripe_subscription_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.stripe_customer} - {self.subscription_plan.name} ({self.status})"
