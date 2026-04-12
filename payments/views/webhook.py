import logging

import stripe
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..services import StripeWebhookService

logger = logging.getLogger(__name__)


@csrf_exempt  # Stripe からの POST は CSRF トークンを持たないため除外
@require_POST  # POST 以外は 405 を返す
def webhook_view(request: HttpRequest) -> HttpResponse:
    """Stripe Webhook を受け取って処理する.

    1. リクエストの署名を検証（改ざん防止）
    2. イベントタイプに応じてハンドラを呼び出し
    3. 成功なら 200、失敗なら 500 を返す（500 なら Stripe が自動リトライ）
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    # 署名検証: 失敗したら 400 を返す（不正リクエスト、リトライ不要）
    try:
        event = StripeWebhookService.verify_webhook(payload, sig_header)
    except (ValueError, stripe.error.SignatureVerificationError):
        logger.warning("Webhook signature verification failed")
        return HttpResponse(status=400)

    data = event["data"]["object"]
    event_type = event["type"]
    logger.info("Webhook received: %s", event_type)

    # イベントタイプごとに処理を分岐
    # 例外が発生した場合は 500 を返し、Stripe に自動リトライさせる
    try:
        match event_type:
            case "checkout.session.completed":
                # Checkout 完了 → CheckoutSession.status を completed に
                # type=credit なら CreditHistory INSERT、type=custom なら InvoiceHistory INSERT
                StripeWebhookService.handle_checkout_completed(data)
            case "customer.subscription.created":
                # サブスク契約 → SubscriptionHistory INSERT
                StripeWebhookService.handle_subscription_created(data)
            case "customer.subscription.updated":
                # サブスク更新（月次更新/プラン変更）→ SubscriptionHistory UPDATE
                StripeWebhookService.handle_subscription_updated(data)
            case "customer.subscription.deleted":
                # サブスク解約 → SubscriptionHistory UPDATE (deleted)
                StripeWebhookService.handle_subscription_deleted(data)
            case "charge.refunded":
                # 返金 → CreditHistory / InvoiceHistory UPDATE (refunded)
                StripeWebhookService.handle_charge_refunded(data)
    except Exception:
        logger.exception("Webhook handler failed: event_type=%s", event_type)
        return HttpResponse(status=500)

    return HttpResponse(status=200)
