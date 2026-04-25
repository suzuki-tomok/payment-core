"""payment app を叩くデモ画面 (動作確認用).

このアプリは payment app の consumer の見本でもある:
    - フォームから入力を受け取り CheckoutInput を構築
    - payment.api.create_checkout_url を呼び、返ってきた URL に redirect
    - 別フォームから order_id を受け取り get_payment_status で状態確認
"""

import uuid

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from payment.api import (
    CheckoutInput,
    DuplicateOrderError,
    InvalidInputError,
    PaymentConfigError,
    PaymentStatus,
    PaymentSystemError,
    create_checkout_url,
    get_payment_status,
)


@require_GET
def index_view(request: HttpRequest) -> HttpResponse:
    """起票フォーム + 結果確認フォームを表示."""
    # order_id のデフォルト値はランダム生成 (二重起票防止のため)
    return render(request, "demo/index.html", {
        "default_order_id": f"demo-{uuid.uuid4().hex[:8]}",
        "default_company_id": "comp-test-001",
        "default_company_name": "テスト株式会社",
        "default_amount": 5000,
        "default_description": "テスト決済",
    })


@require_POST
def checkout_view(request: HttpRequest) -> HttpResponse:
    """フォーム入力を受けて payment app の create_checkout_url を呼ぶ."""
    try:
        input = CheckoutInput(
            order_id=request.POST.get("order_id", "").strip(),
            company_id=request.POST.get("company_id", "").strip(),
            company_name=request.POST.get("company_name", "").strip(),
            amount=int(request.POST.get("amount", "0")),
            description=request.POST.get("description", "").strip(),
        )
    except (ValueError, InvalidInputError) as e:
        return _render_error(request, f"入力エラー: {e}")

    try:
        url = create_checkout_url(input)
    except DuplicateOrderError as e:
        return _render_error(request, f"二重起票: order_id={e.order_id}")
    except PaymentSystemError as e:
        return _render_error(request, f"一時障害 (リトライしてください): {e}")
    except PaymentConfigError as e:
        return _render_error(request, f"設定エラー: {e}")

    return redirect(url)


@require_GET
def status_view(request: HttpRequest) -> HttpResponse:
    """order_id で決済状態を確認."""
    order_id = request.GET.get("order_id", "").strip()
    status: PaymentStatus | None = None
    if order_id:
        status = get_payment_status(order_id)

    return render(request, "demo/status.html", {
        "order_id": order_id,
        "status": status,
    })


def _render_error(request: HttpRequest, message: str) -> HttpResponse:
    """エラー時はフォーム再表示 + メッセージ."""
    return render(request, "demo/index.html", {
        "error": message,
        "default_order_id": request.POST.get("order_id", ""),
        "default_company_id": request.POST.get("company_id", ""),
        "default_company_name": request.POST.get("company_name", ""),
        "default_amount": request.POST.get("amount", ""),
        "default_description": request.POST.get("description", ""),
    })
