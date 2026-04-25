from django.db import models

from .stripe_customer import StripeCustomer


class Payment(models.Model):
    """Stripe Checkout Session の lifecycle と決済結果を1テーブルで表現."""

    class SessionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        SUCCEEDED = "succeeded", "Succeeded"
        REFUNDED = "refunded", "Refunded"

    stripe_customer = models.ForeignKey(
        StripeCustomer, on_delete=models.PROTECT, related_name="payments",
    )
    order_id = models.CharField(max_length=255, unique=True)
    stripe_session_id = models.CharField(max_length=255, unique=True)
    stripe_payment_id = models.CharField(max_length=255, unique=True)
    amount = models.IntegerField()
    description = models.CharField(max_length=255)
    session_status = models.CharField(
        max_length=20,
        choices=SessionStatus.choices,
        default=SessionStatus.PENDING,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.order_id} ({self.session_status}/{self.payment_status})"
