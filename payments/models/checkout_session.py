from django.db import models

from .stripe_customer import StripeCustomer


class CheckoutSession(models.Model):
    class Type(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        CREDIT = "credit", "Credit"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"

    stripe_customer = models.ForeignKey(StripeCustomer, on_delete=models.CASCADE, related_name="checkout_sessions")
    stripe_session_id = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.type} session: {self.stripe_session_id} ({self.status})"
