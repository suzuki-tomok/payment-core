import logging

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import WebhookEventLog
from ..services import StripeWebhookService

logger = logging.getLogger(__name__)


@csrf_exempt  # Stripe からの POST は CSRF トークンを持たないため除外
@require_POST  # POST 以外は 405 を返す
def webhook_view(request: HttpRequest) -> HttpResponse:
    """Stripe Webhook を受け取って処理する.

    1. リクエストの署名を検証（改ざん防止）
    2. 冪等性チェック（処理済みイベントはスキップ）
    3. イベントタイプに応じてハンドラを呼び出し
    4. 成功なら 200、失敗なら 500 を返す（500 なら Stripe が自動リトライ）
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    # 署名検証
    try:
        event = StripeWebhookService.verify_webhook(payload, sig_header)
    except Exception:
        logger.warning("Webhook signature verification failed")
        return HttpResponse(status=400)

    event_id = event["id"]
    event_type = event["type"]
    data = event["data"]["object"]
    stripe_customer_id = data["customer"]

    # 冪等性チェック: 処理済みならスキップ
    if WebhookEventLog.objects.filter(event_id=event_id).exists():
        logger.info("Webhook already processed: %s (%s) customer=%s", event_id, event_type, stripe_customer_id)
        return HttpResponse(status=200)

    logger.info("Webhook received: %s (%s) customer=%s", event_id, event_type, stripe_customer_id)

    # イベントタイプごとに処理を分岐
    try:
        match event_type:
            case "checkout.session.completed":
                StripeWebhookService.handle_checkout_completed(data)
            case "checkout.session.expired":
                StripeWebhookService.handle_checkout_expired(data)
            case "customer.subscription.created":
                StripeWebhookService.handle_subscription_created(data)
            case "customer.subscription.updated":
                StripeWebhookService.handle_subscription_updated(data)
            case "customer.subscription.deleted":
                StripeWebhookService.handle_subscription_deleted(data)
            case "charge.refunded":
                StripeWebhookService.handle_charge_refunded(data)

        # 処理成功 → イベントログに記録
        WebhookEventLog.objects.create(
            event_id=event_id,
            event_type=event_type,
            stripe_customer_id=stripe_customer_id,
        )
    except Exception:
        logger.exception("Webhook handler failed: %s (%s) customer=%s", event_id, event_type, stripe_customer_id)
        return HttpResponse(status=500)

    return HttpResponse(status=200)
