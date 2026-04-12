from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from import_export.admin import ExportMixin

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
    User,
)
from .resources import (
    CheckoutSessionResource,
    CompanyResource,
    CompanyUsageHistoryResource,
    CreditHistoryResource,
    CreditPlanResource,
    StripeCustomerResource,
    SubscriptionHistoryResource,
    SubscriptionPlanResource,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):  # type: ignore[type-arg]
    list_display = ("username", "company", "is_staff", "is_active")
    list_filter = ("company", "is_staff", "is_active")
    fieldsets = [
        *(BaseUserAdmin.fieldsets or []),
        ("会社情報", {"fields": ("company",)}),
    ]
    add_fieldsets = [
        *BaseUserAdmin.add_fieldsets,
        ("会社情報", {"fields": ("company",)}),
    ]


@admin.register(Company)
class CompanyAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = CompanyResource
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(StripeCustomer)
class StripeCustomerAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = StripeCustomerResource
    list_display = ("id", "company", "stripe_customer_id", "created_at")
    search_fields = ("stripe_customer_id", "company__name")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = SubscriptionPlanResource
    list_display = ("id", "name", "stripe_price_id", "monthly_document_limit", "monthly_ai_chat_limit")
    search_fields = ("name",)


@admin.register(SubscriptionHistory)
class SubscriptionHistoryAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = SubscriptionHistoryResource
    list_display = (
        "id", "stripe_customer", "subscription_plan", "status", "current_period_start", "current_period_end",
    )
    list_filter = ("status",)
    search_fields = ("stripe_subscription_id",)


@admin.register(CreditPlan)
class CreditPlanAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = CreditPlanResource
    list_display = ("id", "name", "stripe_price_id", "document_credits", "ai_chat_credits")
    search_fields = ("name",)


@admin.register(CreditHistory)
class CreditHistoryAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = CreditHistoryResource
    list_display = ("id", "stripe_customer", "credit_plan", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("stripe_payment_id",)


@admin.register(CompanyUsageHistory)
class CompanyUsageHistoryAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = CompanyUsageHistoryResource
    list_display = ("id", "company", "user", "type", "source", "created_at")
    list_filter = ("type", "source")
    search_fields = ("company__name",)


@admin.register(InvoiceHistory)
class InvoiceHistoryAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("id", "stripe_customer", "description", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("description", "stripe_payment_id")


@admin.register(CheckoutSession)
class CheckoutSessionAdmin(ExportMixin, admin.ModelAdmin):  # type: ignore[type-arg]
    resource_class = CheckoutSessionResource
    list_display = ("id", "stripe_customer", "type", "status", "created_at")
    list_filter = ("type", "status")
    search_fields = ("stripe_session_id",)
