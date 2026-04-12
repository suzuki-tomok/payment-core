from import_export import resources

from .models import (
    CheckoutSession,
    Company,
    CompanyUsageHistory,
    CreditHistory,
    CreditPlan,
    InvoiceHistory,
    StripeCustomer,
    SubscriptionHistory,
    SubscriptionPlan,
)


class CompanyResource(resources.ModelResource):
    class Meta:
        model = Company


class StripeCustomerResource(resources.ModelResource):
    class Meta:
        model = StripeCustomer


class SubscriptionPlanResource(resources.ModelResource):
    class Meta:
        model = SubscriptionPlan


class SubscriptionHistoryResource(resources.ModelResource):
    class Meta:
        model = SubscriptionHistory


class CreditPlanResource(resources.ModelResource):
    class Meta:
        model = CreditPlan


class CreditHistoryResource(resources.ModelResource):
    class Meta:
        model = CreditHistory


class CompanyUsageHistoryResource(resources.ModelResource):
    class Meta:
        model = CompanyUsageHistory


class InvoiceHistoryResource(resources.ModelResource):
    class Meta:
        model = InvoiceHistory


class CheckoutSessionResource(resources.ModelResource):
    class Meta:
        model = CheckoutSession
