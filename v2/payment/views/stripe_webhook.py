"""Stripe webhook 受信エンドポイント. 署名検証 + 冪等性チェック + dispatch."""

import logging

import stripe
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payment.models import StripeWebhookEventLog
from payment.services import StripeWebhookHandlers

# Stripe SDK の api_key / api_version は payment.services.__init__.py で初期化済

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook_view(request: HttpRequest) -> HttpResponse:
    """Stripe からの webhook を受信して dispatch する.

    HTTP status の方針:
        200: 受領完了 (再送不要)
        400: payload/署名 不正 (再送無意味)
        500: 我々側の処理失敗 (Stripe が自動リトライ)
        502: Stripe API 障害 (Stripe にリトライさせる)
        503: Stripe レート制限 (Stripe にリトライさせる)
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    # 1. 署名検証 (失敗 → 400, リトライさせない)
    try:
        event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.SignatureVerificationError:
        logger.warning("Webhook signature verification failed")
        return HttpResponse(status=400)
    except ValueError:
        # JSON parse 失敗 / thin event (v2 通知を v1 ハンドラで受信)
        logger.warning("Webhook payload invalid (json or thin event)")
        return HttpResponse(status=400)

    event_id = event["id"]
    event_type = event["type"]
    data = event["data"]["object"]

    # 2. 冪等性チェック (既処理ならスキップ)
    if StripeWebhookEventLog.objects.filter(event_id=event_id).exists():
        logger.info("Webhook already processed: %s (%s)", event_id, event_type)
        return HttpResponse(status=200)

    # 3. 想定外 event_type のチェック (Dashboard で設定漏れ等の検知)
    if event_type not in {
        "checkout.session.completed",
        "checkout.session.expired",
        "charge.refunded",
    }:
        logger.warning("Unhandled webhook event type: %s (event_id=%s)", event_type, event_id)
        # 200 を返して受領完了扱い (Stripe にリトライさせない). EventLog は記録しない.
        return HttpResponse(status=200)

    logger.info("Webhook received: %s (%s)", event_id, event_type)

    # 4. 事前 fetch: checkout.session.completed の line_items は payload に含まれず、
    # 後段の atomic 内で外部 API を呼ばないように先に取得する.
    pre_fetched_line_item = None
    if event_type == "checkout.session.completed":
        try:
            session = stripe.checkout.Session.retrieve(data["id"], expand=["line_items"])
            # expand=["line_items"] 指定したので line_items は必ず返る
            assert session.line_items is not None  # noqa: S101
            pre_fetched_line_item = session.line_items.data[0]
        except stripe.RateLimitError as e:
            logger.warning("Stripe rate limit on retrieve: req=%s", e.request_id)
            return HttpResponse(status=503)
        except stripe.APIConnectionError as e:
            logger.warning("Stripe connection error on retrieve: req=%s", e.request_id)
            return HttpResponse(status=502)
        except stripe.StripeError as e:
            logger.exception("Stripe error on retrieve: req=%s type=%s", e.request_id, type(e).__name__)
            return HttpResponse(status=502)

    # 5. atomic 内で handler の DB 更新 + EventLog を同一 tx に
    try:
        with transaction.atomic():
            match event_type:
                case "checkout.session.completed":
                    StripeWebhookHandlers.handle_checkout_completed(data, pre_fetched_line_item)
                case "checkout.session.expired":
                    StripeWebhookHandlers.handle_checkout_expired(data)
                case "charge.refunded":
                    StripeWebhookHandlers.handle_charge_refunded(data)
                case _:
                    # 上の event_type フィルタを通過してるのでここには来ないはず.
                    # 来たら不整合 (フィルタと match の食い違い) = 実装バグ → 500.
                    logger.error("Logic mismatch: event_type %s passed filter but no case", event_type)
                    return HttpResponse(status=500)

            StripeWebhookEventLog.objects.create(
                event_id=event_id,
                event_type=event_type,
            )
    except Exception:
        # 想定外の例外. Stripe に再送させてリトライ.
        logger.exception("Webhook handler failed: %s (%s)", event_id, event_type)
        return HttpResponse(status=500)

    return HttpResponse(status=200)
