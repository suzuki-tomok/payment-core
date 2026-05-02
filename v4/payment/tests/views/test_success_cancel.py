"""success_view / cancel_view (GET) の HTTP テスト.

success/cancel view は DB 操作を行わず、画面表示のみ.
order_id があってもなくても 200 を返す (Payment 存在チェックなし).
"""

from django.test import Client


def test_success_renders_200(client: Client):
    """success: order_id 付きで 200 + template render."""
    response = client.get("/payment/checkout/success/?order_id=ord-1")

    assert response.status_code == 200
    assert b"ord-1" in response.content


def test_success_renders_200_without_order_id(client: Client):
    """success: order_id 無しでも 200 (DB チェックなし)."""
    response = client.get("/payment/checkout/success/")

    assert response.status_code == 200


def test_cancel_renders_200(client: Client):
    """cancel: 200 + template render. DB 操作なし."""
    response = client.get("/payment/checkout/cancel/?order_id=ord-1")

    assert response.status_code == 200
    assert b"ord-1" in response.content


def test_cancel_renders_200_without_order_id(client: Client):
    """cancel: order_id 無しでも 200."""
    response = client.get("/payment/checkout/cancel/")

    assert response.status_code == 200
