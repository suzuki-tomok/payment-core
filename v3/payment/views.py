"""payment app の view. Stripe Checkout 起票 API + Stripe webhook 受信エンドポイント."""

import json
import logging
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from payment.models import Payment, StripeWebhookEventLog
from payment.services.checkout import PaymentStatus, create_checkout_url, get_payment_status
from payment.services.dtos import CheckoutInput
from payment.services.exceptions import DuplicateOrderError, InvalidInputError
from payment.services.webhook_handlers import (
    handle_charge_refunded,
    handle_checkout_completed,
    handle_checkout_expired,
)
from payment.stripe import (
    ConstructWebhookEventInput,
    ConstructWebhookEventOutput,
    GetCompletedSessionDetailsOutput,
    PaymentConfigError,
    PaymentSystemError,
    WebhookSignatureError,
    get_stripe_client,
)

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def create_checkout_view(request: HttpRequest) -> HttpResponse:
    """決済を起票して Stripe Checkout の URL を返す.

    Request body (JSON):
        {order_id, company_id, company_name, amount, description}

    HTTP status の方針:
        200: 起票成功. body に Checkout URL.
        400: JSON 不正 / 入力バリデーション失敗 (caller が修正)
        409: 同 order_id で既に起票済 (caller が修正)
        500: Stripe 恒久エラー (auth / API 不整合 — 我々側のバグ)
        502: Stripe 一時障害 (caller がリトライ可)

    Note:
        @csrf_exempt: 想定 caller は service-to-service. session-based client から
        呼ぶ場合は CSRF トークン要件を別途検討すること.
    """
    # 1. JSON parse
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    # 2. success / cancel URL を組み立て (path は reverse, クエリは urlencode で安全に).
    # build_absolute_uri で request の host を絶対 URL に展開.
    order_id = body.get("order_id", "")
    qs = urlencode({"order_id": order_id})
    success_url = request.build_absolute_uri(f"{reverse('payment:checkout_success')}?{qs}")
    cancel_url = request.build_absolute_uri(f"{reverse('payment:checkout_cancel')}?{qs}")

    # 3. CheckoutInput 構築 (__post_init__ でバリデーション).
    # 不足フィールドは get(..., "") で空文字 → InvalidInputError に集約される.
    try:
        checkout_input = CheckoutInput(
            order_id=order_id,
            company_id=body.get("company_id", ""),
            company_name=body.get("company_name", ""),
            amount=body.get("amount", 0),
            description=body.get("description", ""),
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except InvalidInputError as e:
        return JsonResponse({"error": str(e)}, status=400)

    # 4. service 呼び出し. 各例外を HTTP status にマッピング.
    try:
        url = create_checkout_url(checkout_input)
    except DuplicateOrderError as e:
        # 二重起票. caller は order_id をユニークに採番すべき.
        logger.info("Duplicate order: %s", e.order_id)
        return JsonResponse({"error": "duplicate_order", "order_id": e.order_id}, status=409)
    except PaymentSystemError:
        # Stripe 一時障害. caller がリトライ可.
        logger.warning("Stripe transient error on create_checkout: order_id=%s", checkout_input.order_id)
        return JsonResponse({"error": "stripe_transient"}, status=502)
    except PaymentConfigError:
        # Stripe 恒久エラー. 我々側の設定 / 実装バグ.
        logger.exception("Stripe permanent error on create_checkout: order_id=%s", checkout_input.order_id)
        return JsonResponse({"error": "stripe_permanent"}, status=500)

    return JsonResponse({"url": url})


@require_GET
def success_view(request: HttpRequest) -> HttpResponse:
    """Stripe success_url の戻り先. ポーリング画面 (skeleton) を表示.

    画面の実データ (amount / description / status) は JS が status_view から fetch して
    populate する. 表示時点では Payment は PENDING のままの可能性があり (webhook 未着),
    JS のポーリングで SUCCEEDED に変わるのを待つ.
    """
    order_id = request.GET.get("order_id", "")
    payment = Payment.objects.filter(order_id=order_id).only("order_id").first()
    if payment is None:
        raise Http404("order_id not found")
    return render(request, "payment/success.html", {"order_id": payment.order_id})


@require_GET
def cancel_view(request: HttpRequest) -> HttpResponse:
    """Stripe cancel_url の戻り先. キャンセル画面を表示 + DB を canceled に更新.

    Stripe は checkout.session.canceled webhook を投げないため、ここで
    pending → canceled に更新する. 後で webhook で completed が来た場合は
    handler 側が SUCCEEDED で上書きする (succeeded が真).
    """
    order_id = request.GET.get("order_id", "")
    payment = Payment.objects.filter(order_id=order_id).only(
        "id", "order_id", "session_status",
    ).first()
    if payment is None:
        raise Http404("order_id not found")

    # pending のみ canceled に更新. expired / completed 等は触らない.
    # .update() は auto_now を発火しないため updated_at を明示セット.
    if payment.session_status == Payment.SessionStatus.PENDING:
        Payment.objects.filter(pk=payment.pk).update(
            session_status=Payment.SessionStatus.CANCELED,
            updated_at=timezone.now(),
        )

    return render(request, "payment/cancel.html", {"order_id": payment.order_id})


@require_GET
def status_view(request: HttpRequest) -> HttpResponse:
    """GET /payment/status/?order_id=xxx で決済状態 + 表示用データを返す.

    success.html の JS が polling する内部 API. 公開 API ではない.

    レスポンス:
        200: {"status": "succeeded", "amount": 5000, "description": "..."}
        400: {"error": "order_id required"}
        404: {"error": "not_found"}
    """
    # 1. order_id バリデーション
    order_id = request.GET.get("order_id", "")
    if not order_id:
        return JsonResponse({"error": "order_id required"}, status=400)

    # 2. 公開 status 取得 (NOT_FOUND なら 404)
    status = get_payment_status(order_id)
    if status == PaymentStatus.NOT_FOUND:
        return JsonResponse({"error": "not_found"}, status=404)

    # 3. 表示用データ (amount, description) を別途取得.
    # status != NOT_FOUND 判定後に別 tx が削除した極低確率 race のみ None になり得る.
    # 契約違反として明示的に surface (assert は -O で消えるので使わない).
    payment = Payment.objects.filter(order_id=order_id).only(
        "amount", "description",
    ).first()
    if payment is None:
        raise RuntimeError(
            f"Payment row vanished after status check: order_id={order_id}",
        )

    return JsonResponse({
        "status": status.value,
        "amount": payment.amount,
        "description": payment.description,
    })


@require_GET
def mock_checkout_view(request: HttpRequest, session_id: str) -> HttpResponse:
    """USE_MOCK_STRIPE=True 時の疑似 Checkout 中継. 踏んだら自動成功扱いで success_url にリダイレクト.

    本物の Stripe を叩けない開発者向け. UI は無く、checkout.session.completed の handler を
    内部で発火して Payment を SUCCEEDED にしてから success_url に飛ばす.
    本番では USE_MOCK_STRIPE=False にすること (False なら 404).
    """
    if not settings.USE_MOCK_STRIPE:
        raise Http404

    # client_mock の遅延 import (USE_MOCK_STRIPE=False 時にロードしない).
    from payment.stripe.client_mock import StripeClientMock

    client = get_stripe_client()
    assert isinstance(client, StripeClientMock)  # noqa: S101  USE_MOCK_STRIPE=True なので必ず Mock

    # mock の in-memory session 情報を取得 (amount / description / success_url).
    # create_checkout_session 時に保存されている.
    mock_session = client._sessions.get(session_id)
    if mock_session is None:
        raise Http404("mock session not found")

    # 偽 webhook event + line_item details を組み立て、本物 webhook と同じ handler を呼ぶ.
    # (signature 検証 / JSON parse は mock 経路では無いので飛ばすが、それ以外は同じ code path.)
    event = ConstructWebhookEventOutput(
        event_id=f"evt_mock_{uuid.uuid4().hex[:14]}",
        event_type="checkout.session.completed",
        data={"id": session_id},
    )
    details = GetCompletedSessionDetailsOutput(
        amount=mock_session["amount"],
        description=mock_session["description"],
        payment_intent_id=mock_session["payment_intent_id"],
    )

    # handler + EventLog を本物 stripe_webhook_view と同じ atomic で実行.
    try:
        with transaction.atomic():
            handle_checkout_completed(event, details)
            StripeWebhookEventLog.objects.create(
                event_id=event.event_id, event_type=event.event_type,
            )
    except Exception:
        # mock は dev 用なので failure 時はログだけ出して続行 (success_url にリダイレクトはする).
        logger.exception("Mock checkout completion failed: session_id=%s", session_id)

    logger.info("Mock checkout auto-completed: session_id=%s", session_id)
    return redirect(mock_session["success_url"])


@csrf_exempt
@require_POST
def stripe_webhook_view(request: HttpRequest) -> HttpResponse:
    """Stripe からの webhook を受信して dispatch する.

    HTTP status の方針:
        200: 受領完了 (再送不要)
        400: 署名 / payload 不正 (再送無意味)
        500: 我々側の処理失敗 (Stripe にリトライさせる)
        502: Stripe 一時障害で事前 fetch 失敗 (Stripe にリトライさせる)
    """
    client = get_stripe_client()

    # 1. 署名検証 + parse (StripeClient で密閉. stripe.* は触らない)
    try:
        event = client.construct_webhook_event(ConstructWebhookEventInput(
            payload=request.body,
            sig_header=request.META.get("HTTP_STRIPE_SIGNATURE", ""),
            secret=settings.STRIPE_WEBHOOK_SECRET,
        ))
    except WebhookSignatureError:
        # 署名検証失敗 / JSON 不正 / thin event → 400 (Stripe にリトライさせない)
        logger.warning("Webhook signature verification failed")
        return HttpResponse(status=400)

    # 2. 冪等性チェック (既処理ならスキップ. EventLog の event_id unique 制約と二重防御)
    if StripeWebhookEventLog.objects.filter(event_id=event.event_id).exists():
        logger.info("Webhook already processed: %s (%s)", event.event_id, event.event_type)
        return HttpResponse(status=200)

    logger.info("Webhook received: %s (%s)", event.event_id, event.event_type)

    # 3. event_type ごとに分岐. 各ブランチが atomic + EventLog を持つ自己完結型.

    # checkout.session.completed: 顧客が支払いを完了した時に発火.
    # Payment を SUCCEEDED に更新し、Stripe 側の確定額 / 説明を反映する.
    if event.event_type == "checkout.session.completed":
        # line_items は payload に含まれないため別途 retrieve. atomic 外で実施し tx を引っ張らない.
        try:
            details = client.get_completed_session_details(event.data["id"])
        except PaymentSystemError:
            # Stripe 一時障害 → Stripe にリトライさせる
            logger.warning("Stripe transient error on retrieve: %s", event.event_id)
            return HttpResponse(status=502)
        except PaymentConfigError:
            # session 不存在 / API key 不正等 → 我々側のバグ
            logger.exception("Stripe permanent error on retrieve: %s", event.event_id)
            return HttpResponse(status=500)

        try:
            with transaction.atomic():
                handle_checkout_completed(event, details)
                # handler は Payment 更新のみ. EventLog (冪等性キー) は同一 tx で view 側が書く.
                StripeWebhookEventLog.objects.create(
                    event_id=event.event_id, event_type=event.event_type,
                )
        except Exception:
            # DB 障害 / EventLog の IntegrityError (同時実行) 等 → Stripe に再送させる
            logger.exception(
                "Webhook handler failed: %s (%s)", event.event_id, event.event_type,
            )
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    # checkout.session.expired: Session が期限切れ (default 24h で未完了) になった時に発火.
    # session_status のみ EXPIRED に更新し、payment_status (UNPAID) は触らない.
    if event.event_type == "checkout.session.expired":
        try:
            with transaction.atomic():
                handle_checkout_expired(event)
                # handler は Payment 更新のみ. EventLog (冪等性キー) は同一 tx で view 側が書く.
                StripeWebhookEventLog.objects.create(
                    event_id=event.event_id, event_type=event.event_type,
                )
        except Exception:
            logger.exception(
                "Webhook handler failed: %s (%s)", event.event_id, event.event_type,
            )
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    # charge.refunded: 決済完了後に Dashboard / API から返金された時に発火.
    # payment_status を REFUNDED に更新. payload に session_id は無く payment_intent_id 経由で検索 (handler 側).
    if event.event_type == "charge.refunded":
        try:
            with transaction.atomic():
                handle_charge_refunded(event)
                # handler は Payment 更新のみ. EventLog (冪等性キー) は同一 tx で view 側が書く.
                StripeWebhookEventLog.objects.create(
                    event_id=event.event_id, event_type=event.event_type,
                )
        except Exception:
            logger.exception(
                "Webhook handler failed: %s (%s)", event.event_id, event.event_type,
            )
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    # 想定外 event_type (Dashboard 設定漏れ等). 200 で受領済扱い (Stripe にリトライさせない).
    # EventLog は記録しない: 実際に処理してないので「処理済」フラグを残さない.
    logger.warning(
        "Unhandled webhook event type: %s (event_id=%s)",
        event.event_type, event.event_id,
    )
    return HttpResponse(status=200)
