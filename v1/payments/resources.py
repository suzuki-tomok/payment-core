from import_export import resources

from .models import (
    CheckoutSessionStatus,
    Company,
    CompanyUsageHistory,
    CreditPlan,
    CreditStatus,
    InvoiceStatus,
    StripeCustomer,
    SubscriptionPlan,
    SubscriptionStatus,
    WebhookEventLog,
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


class SubscriptionStatusResource(resources.ModelResource):
    class Meta:
        model = SubscriptionStatus


class CreditPlanResource(resources.ModelResource):
    class Meta:
        model = CreditPlan


class CreditStatusResource(resources.ModelResource):
    class Meta:
        model = CreditStatus


class CompanyUsageHistoryResource(resources.ModelResource):
    class Meta:
        model = CompanyUsageHistory


class InvoiceStatusResource(resources.ModelResource):
    class Meta:
        model = InvoiceStatus


class CheckoutSessionStatusResource(resources.ModelResource):
    class Meta:
        model = CheckoutSessionStatus


class WebhookEventLogResource(resources.ModelResource):
    class Meta:
        model = WebhookEventLog
