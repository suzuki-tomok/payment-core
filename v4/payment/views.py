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
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from payment.models import StripeWebhookEventLog
from payment.services.checkout import create_checkout_url
from payment.services.dtos import CheckoutInput
from payment.services.exceptions import InvalidInputError, WebhookContractError
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
        500: Stripe 恒久エラー (auth / API 不整合 — 我々側のバグ)
        502: Stripe 一時障害 (caller がリトライ可)

    Note:
        二重起票の検知 (DuplicateOrderError) は行わない設計.
        同 order_id + 同 amount で再 POST すると Stripe 側 idempotency_key の cache hit で
        同じ Session URL が返る (24h 有効). amount 変更時は新 Session が作られる.
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
    except PaymentSystemError:
        # Stripe 一時障害. caller がリトライ可.
        logger.warning(
            "Stripe transient error on create_checkout",
            extra={"order_id": checkout_input.order_id},
        )
        return JsonResponse({"error": "stripe_transient"}, status=502)
    except PaymentConfigError:
        # Stripe 恒久エラー. 我々側の設定 / 実装バグ.
        logger.exception(
            "Stripe permanent error on create_checkout",
            extra={"order_id": checkout_input.order_id},
        )
        return JsonResponse({"error": "stripe_permanent"}, status=500)

    return JsonResponse({"url": url})


@require_GET
def success_view(request: HttpRequest) -> HttpResponse:
    """Stripe success_url の戻り先. 「決済を受け付けました」を表示するだけ.

    webhook が真実なので、この画面では DB チェックも polling も行わない.
    決済結果は注文一覧などで反映を確認してもらう (数秒〜数分の遅延あり).
    """
    order_id = request.GET.get("order_id", "")
    return render(request, "payment/success.html", {"order_id": order_id})


@require_GET
def cancel_view(request: HttpRequest) -> HttpResponse:
    """Stripe cancel_url の戻り先. キャンセル画面を表示するだけ.

    Payment は webhook 成功時のみ作成されるため、cancel_view では
    DB 操作は不要 (元々レコードが無い). ユーザは普通に再度「決済する」を押せば
    新 Session で続行できる.
    """
    order_id = request.GET.get("order_id", "")
    return render(request, "payment/cancel.html", {"order_id": order_id})


@require_GET
def mock_checkout_view(request: HttpRequest, session_id: str) -> HttpResponse:
    """USE_MOCK_STRIPE=True 時の疑似 Checkout 中継.

    踏んだら自動成功扱いで success_url にリダイレクトする dev 用 view.
    本物の Stripe を叩けない開発者向け. UI は無く、checkout.session.completed の handler を
    内部で発火して Payment を作成してから success_url に飛ばす.
    本番では USE_MOCK_STRIPE=False にすること (False なら 404).
    """
    if not settings.USE_MOCK_STRIPE:
        raise Http404

    # client_mock の遅延 import (USE_MOCK_STRIPE=False 時にロードしない).
    from payment.stripe.client_mock import StripeClientMock

    client = get_stripe_client()
    # USE_MOCK_STRIPE=True なら apps.py で StripeClientMock が DI されてるはず.
    # 違うクラスが返るのは設定不整合 = 本番事故防止のため明示的に止める (-O でも消えない).
    if not isinstance(client, StripeClientMock):
        raise RuntimeError(
            "USE_MOCK_STRIPE=True but get_stripe_client() returned a non-mock client. "
            "Check apps.py wiring.",
        )

    # mock の in-memory session 情報を取得 (amount / description / success_url / metadata).
    mock_session = client._sessions.get(session_id)
    if mock_session is None:
        raise Http404("mock session not found")

    # 偽 webhook event を組み立てて handler を呼ぶ.
    # 本物 webhook と同じく event.data に customer / metadata / id を含める.
    event = ConstructWebhookEventOutput(
        event_id=f"evt_mock_{uuid.uuid4().hex[:14]}",
        event_type="checkout.session.completed",
        data={
            "id": session_id,
            "customer": mock_session["customer_id"],
            "metadata": mock_session["metadata"],
        },
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

    ログ方針 (forensics 用):
        - 受信時に raw body + 署名 header を必ず log (署名検証より前 → 失敗時も残る)
        - 署名検証成功後は parse 済 event 全体を log
        - DB には冪等性キー (event_id) しか保存しない. 生 payload は log aggregation
          (Datadog/CloudWatch 等) 側で保持する設計.
    """
    client = get_stripe_client()
    body = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    # 0. 受信 log (署名検証より前. 失敗時の forensics でも raw body が残るように).
    logger.info(
        "Webhook raw received",
        extra={
            "stripe_signature": sig_header,
            "body_size": len(body),
            "body": body.decode("utf-8", errors="replace"),
        },
    )

    # 1. 署名検証 + parse (StripeClient で密閉. stripe.* は触らない)
    try:
        event = client.construct_webhook_event(ConstructWebhookEventInput(
            payload=body,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        ))
    except WebhookSignatureError:
        logger.warning(
            "Webhook signature verification failed",
            extra={"sig_header_prefix": sig_header[:20], "body_size": len(body)},
        )
        return HttpResponse(status=400)

    # 2. 冪等性チェック
    if StripeWebhookEventLog.objects.filter(event_id=event.event_id).exists():
        logger.info(
            "Webhook already processed",
            extra={"event_id": event.event_id, "event_type": event.event_type},
        )
        return HttpResponse(status=200)

    # 3. parse 済 event の構造化 log (data オブジェクト全体を残す).
    logger.info(
        "Webhook event verified",
        extra={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "event_data": event.data,
        },
    )

    # 4. event_type ごとに分岐.

    # checkout.session.completed: 決済成功 → Payment を新規作成.
    if event.event_type == "checkout.session.completed":
        # line_items / payment_intent は payload に含まれないため別途 retrieve.
        # atomic 外で実施し tx を引っ張らない.
        try:
            details = client.get_completed_session_details(event.data["id"])
        except PaymentSystemError:
            logger.warning(
                "Stripe transient error on retrieve",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return HttpResponse(status=502)
        except PaymentConfigError:
            logger.exception(
                "Stripe permanent error on retrieve",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return HttpResponse(status=500)

        try:
            with transaction.atomic():
                handle_checkout_completed(event, details)
                StripeWebhookEventLog.objects.create(
                    event_id=event.event_id, event_type=event.event_type,
                )
        except WebhookContractError:
            # 我々の前提 (metadata / customer 等) を Stripe event が破った場合.
            # 通常起きない = 起票時バグ or 外部由来 event の可能性 → alert worthy.
            logger.exception(
                "Webhook contract violation (alert worthy)",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return HttpResponse(status=500)
        except Exception:
            # DB 障害 / 想定外例外. Stripe にリトライさせる.
            logger.exception(
                "Webhook handler failed (unexpected)",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    # checkout.session.expired: 何もしない (handler 側で no-op log).
    if event.event_type == "checkout.session.expired":
        try:
            with transaction.atomic():
                handle_checkout_expired(event)
                StripeWebhookEventLog.objects.create(
                    event_id=event.event_id, event_type=event.event_type,
                )
        except Exception:
            logger.exception(
                "Webhook handler failed",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    # charge.refunded: Payment.is_refunded を True に.
    if event.event_type == "charge.refunded":
        try:
            with transaction.atomic():
                handle_charge_refunded(event)
                StripeWebhookEventLog.objects.create(
                    event_id=event.event_id, event_type=event.event_type,
                )
        except Exception:
            logger.exception(
                "Webhook handler failed",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return HttpResponse(status=500)
        return HttpResponse(status=200)

    # 想定外 event_type. 200 で受領済扱い (Stripe にリトライさせない).
    logger.warning(
        "Unhandled webhook event type",
        extra={"event_id": event.event_id, "event_type": event.event_type},
    )
    return HttpResponse(status=200)
