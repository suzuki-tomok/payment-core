import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from ..models import CheckoutSession, CreditPlan, SubscriptionPlan, User
from ..services import StripeService


@login_required
def subscription_checkout_view(request: HttpRequest) -> HttpResponse:
    """サブスクリプション Checkout.

    1. StripeCustomer を取得/作成
    2. ダッシュボードで選択された plan_id から SubscriptionPlan を取得
    3. Stripe に Checkout Session を作成
    4. Stripe の決済画面にリダイレクト
    """
    if request.method != "POST":
        return redirect("dashboard")

    user: User = request.user  # type: ignore[assignment]
    stripe_customer = StripeService.get_or_create_customer(user.company)
    base_url = request.build_absolute_uri("/")

    plan_id = request.POST.get("plan_id", "")
    plan = SubscriptionPlan.objects.get(id=plan_id)
    session = StripeService.create_subscription_checkout(stripe_customer, plan, base_url)

    return redirect(session.url or "dashboard")


@login_required
def credit_checkout_view(request: HttpRequest) -> HttpResponse:
    """クレジット購入 Checkout.

    1. StripeCustomer を取得/作成
    2. ダッシュボードで選択された credit_plan_id から CreditPlan を取得
    3. Stripe に Checkout Session を作成
    4. Stripe の決済画面にリダイレクト
    """
    if request.method != "POST":
        return redirect("dashboard")

    user: User = request.user  # type: ignore[assignment]
    stripe_customer = StripeService.get_or_create_customer(user.company)
    base_url = request.build_absolute_uri("/")

    credit_plan_id = request.POST.get("credit_plan_id", "")
    credit_plan = CreditPlan.objects.get(id=credit_plan_id)
    session = StripeService.create_credit_checkout(stripe_customer, credit_plan, base_url)

    return redirect(session.url or "dashboard")


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
    """CheckoutSession のステータスを JSON で返す.

    フロントからポーリングで呼ばれる。
    status が completed になったら Webhook 処理完了。
    """
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
