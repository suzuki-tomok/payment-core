from django.db import models

from .company import Company


class StripeCustomer(models.Model):
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="stripe_customer")
    stripe_customer_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.company.name} ({self.stripe_customer_id})"
