import stripe
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..services import StripeService


@csrf_exempt  # Stripe からの POST は CSRF トークンを持たないため除外
@require_POST  # POST 以外は 405 を返す
def webhook_view(request: HttpRequest) -> HttpResponse:
    """Stripe Webhook を受け取って処理する.

    1. リクエストの署名を検証（改ざん防止）
    2. イベントタイプに応じてハンドラを呼び出し
    3. 200 を返す（Stripe にリトライさせないため）
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    # 署名検証: 失敗したら 400 を返す
    try:
        event = StripeService.verify_webhook(payload, sig_header)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    data = event["data"]["object"]
    event_type = event["type"]

    # イベントタイプごとに処理を分岐
    match event_type:
        case "checkout.session.completed":
            # Checkout 完了 → CheckoutSession.status を completed に
            # type=credit なら CreditHistory も作成
            StripeService.handle_checkout_completed(data)
        case "customer.subscription.created":
            # サブスク契約 → SubscriptionHistory 作成
            StripeService.handle_subscription_created(data)
        case "customer.subscription.updated":
            # サブスク更新（月次更新/プラン変更）→ SubscriptionHistory 作成
            StripeService.handle_subscription_updated(data)
        case "customer.subscription.deleted":
            # サブスク解約 → SubscriptionHistory 作成 (canceled)
            StripeService.handle_subscription_deleted(data)

    return HttpResponse(status=200)
