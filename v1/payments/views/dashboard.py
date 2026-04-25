from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from ..models import CreditPlan, SubscriptionPlan, User
from ..services import RemainingCreditService, RemainingSubscriptionService


@login_required
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """ダッシュボード画面."""
    user: User = request.user  # type: ignore[assignment]
    company = user.company

    return render(request, "payments/dashboard.html", {
        "subscription": RemainingSubscriptionService.get_remaining(company),
        "subscription_plans": SubscriptionPlan.objects.all(),
        "credit": RemainingCreditService.get_remaining(company),
        "credit_plans": CreditPlan.objects.all(),
    })
