"""ユーザーブラウザ向けエンドポイント (Stripe からの redirect 受け + polling API)."""

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from payment.api import PaymentStatus, get_payment_status
from payment.models import Payment


def success_view(request: HttpRequest) -> HttpResponse:
    """Stripe success_url のリダイレクト先. ポーリング画面 (skeleton) を表示.

    amount / description / status は JS が /status/ から fetch して populate する.
    """
    # 1. order_id 取得
    order_id = request.GET.get("order_id", "")

    # 2. Payment 検索 (なければ 404)
    payment = Payment.objects.filter(order_id=order_id).only("order_id").first()
    if payment is None:
        raise Http404("order_id not found")

    # 3. ポーリング画面を render (実データは JS が /status/ から取得)
    return render(request, "payment/success.html", {"order_id": payment.order_id})


def cancel_view(request: HttpRequest) -> HttpResponse:
    """Stripe cancel_url のリダイレクト先. キャンセル画面を表示.

    Stripe は checkout.session.canceled webhook を投げないため、ここで
    pending → canceled へ更新する. 後で何らかの理由で webhook で completed
    が来たら、そちらが上書きする (succeeded が真).
    """
    # 1. order_id 取得
    order_id = request.GET.get("order_id", "")

    # 2. Payment 検索 (なければ 404)
    payment = Payment.objects.filter(order_id=order_id).only(
        "id", "order_id", "session_status",
    ).first()
    if payment is None:
        raise Http404("order_id not found")

    # 3. pending なら canceled に更新 (Stripe からは canceled webhook が来ないため)
    if payment.session_status == Payment.SessionStatus.PENDING:
        Payment.objects.filter(pk=payment.pk).update(
            session_status=Payment.SessionStatus.CANCELED,
        )

    # 4. キャンセル画面を render
    return render(request, "payment/cancel.html", {"order_id": payment.order_id})


@require_GET
def status_view(request: HttpRequest) -> HttpResponse:
    """GET /status/?order_id=xxx で決済状態 + 表示用データを返す.

    payment app の success template が JS から fetch する内部 API.
    他アプリは使わない (公開 API は payment.api.get_payment_status).

    レスポンス例:
        {"status": "succeeded", "amount": 5000, "description": "..."}
    レスポンス例 (未発見):
        {"error": "not_found"} (404)
    """
    # 1. order_id バリデーション
    order_id = request.GET.get("order_id", "")
    if not order_id:
        return JsonResponse({"error": "order_id required"}, status=400)

    # 2. 公開 status 取得 (NOT_FOUND なら 404)
    status = get_payment_status(order_id)
    if status == PaymentStatus.NOT_FOUND:
        return JsonResponse({"error": "not_found"}, status=404)

    # 3. 表示用データ (amount, description) を別途取得
    # status != NOT_FOUND だったので Payment は必ず存在する
    payment = Payment.objects.filter(order_id=order_id).only("amount", "description").first()
    assert payment is not None  # noqa: S101

    # 4. JSON 返却 (status + 表示用データ)
    return JsonResponse({
        "status": status.value,
        "amount": payment.amount,
        "description": payment.description,
    })
