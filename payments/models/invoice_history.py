from django.db import models

from .stripe_customer import StripeCustomer


class InvoiceHistory(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        REFUNDED = "refunded", "Refunded"

    stripe_customer = models.ForeignKey(StripeCustomer, on_delete=models.CASCADE, related_name="invoice_histories")
    description = models.CharField(max_length=255)
    amount = models.IntegerField()
    stripe_payment_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.description} ¥{self.amount} ({self.status})"
