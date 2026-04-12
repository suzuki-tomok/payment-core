import json
import logging

import stripe
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from ..models import CheckoutSession, CreditPlan, SubscriptionPlan, User
from ..services import StripeCheckoutService, StripeCheckoutValidator

logger = logging.getLogger(__name__)

ERROR_TEMPLATE = "payments/checkout_error.html"


@login_required
def subscription_checkout_view(request: HttpRequest) -> HttpResponse:
    """サブスクリプション Checkout."""
    if request.method != "POST":
        return redirect("dashboard")

    user: User = request.user  # type: ignore[assignment]
    plan_id = request.POST.get("plan_id", "")

    # バリデーション
    error = StripeCheckoutValidator.validate_subscription(user, plan_id)
    if error:
        return render(request, ERROR_TEMPLATE, {"message": error})

    try:
        stripe_customer = StripeCheckoutService.get_or_create_customer(user.company)
        plan = SubscriptionPlan.objects.get(id=plan_id)
        session = StripeCheckoutService.create_subscription_checkout(
            stripe_customer, plan, request.build_absolute_uri("/"),
        )
        return redirect(session.url or "dashboard")
    except stripe.StripeError:
        logger.exception("Stripe API error in subscription checkout")
        return render(request, ERROR_TEMPLATE, {"message": "決済サービスとの通信に失敗しました。"})


@login_required
def credit_checkout_view(request: HttpRequest) -> HttpResponse:
    """クレジット購入 Checkout."""
    if request.method != "POST":
        return redirect("dashboard")

    credit_plan_id = request.POST.get("credit_plan_id", "")

    # バリデーション
    error = StripeCheckoutValidator.validate_credit(credit_plan_id)
    if error:
        return render(request, ERROR_TEMPLATE, {"message": error})

    try:
        user: User = request.user  # type: ignore[assignment]
        stripe_customer = StripeCheckoutService.get_or_create_customer(user.company)
        credit_plan = CreditPlan.objects.get(id=credit_plan_id)
        session = StripeCheckoutService.create_credit_checkout(
            stripe_customer, credit_plan, request.build_absolute_uri("/"),
        )
        return redirect(session.url or "dashboard")
    except stripe.StripeError:
        logger.exception("Stripe API error in credit checkout")
        return render(request, ERROR_TEMPLATE, {"message": "決済サービスとの通信に失敗しました。"})


@login_required
def custom_checkout_view(request: HttpRequest) -> HttpResponse:
    """カスタム金額 Checkout."""
    if request.method != "POST":
        return redirect("dashboard")

    description = request.POST.get("description", "")

    # バリデーション
    error, amount = StripeCheckoutValidator.validate_custom(
        request.POST.get("amount", "0"), description,
    )
    if error:
        return render(request, ERROR_TEMPLATE, {"message": error})

    try:
        user: User = request.user  # type: ignore[assignment]
        stripe_customer = StripeCheckoutService.get_or_create_customer(user.company)
        session = StripeCheckoutService.create_custom_checkout(
            stripe_customer, amount, description.strip(), request.build_absolute_uri("/"),
        )
        return redirect(session.url or "dashboard")
    except stripe.StripeError:
        logger.exception("Stripe API error in custom checkout")
        return render(request, ERROR_TEMPLATE, {"message": "決済サービスとの通信に失敗しました。"})


@login_required
def checkout_success_view(request: HttpRequest) -> HttpResponse:
    """Checkout 成功画面. Stripe での決済完了後にリダイレクトされる."""
    session_id = request.GET.get("session_id", "")
    return render(request, "payments/checkout_success.html", {"session_id": session_id})


@login_required
def checkout_cancel_view(request: HttpRequest) -> HttpResponse:
    """Checkout キャンセル画面. ユーザーが決済をキャンセルした場合."""
    return render(request, "payments/checkout_cancel.html")


@login_required
def checkout_status_view(request: HttpRequest) -> HttpResponse:
    """CheckoutSession のステータスを JSON で返す."""
    session_id = request.GET.get("session_id", "")

    try:
        checkout = CheckoutSession.objects.get(stripe_session_id=session_id)
        status = checkout.status
    except CheckoutSession.DoesNotExist:
        status = "not_found"

    return HttpResponse(
        json.dumps({"status": status}),
        content_type="application/json",
    )
