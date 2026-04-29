"""success_view / cancel_view (GET) の HTTP テスト.

success: Payment 存在で 200 + template render. 不在で 404.
cancel: PENDING のみ CANCELED に更新. その他は不変. 不在で 404.
"""

import pytest

from payment.models import Payment
from payment.tests.factories import PaymentFactory

# ============================================================================
# success_view
# ============================================================================

@pytest.mark.django_db
def test_success_renders_with_order_id(client):
    """Payment 存在 → 200 + template (order_id を含む)."""
    PaymentFactory(order_id="ord-1")

    response = client.get("/payment/checkout/success/?order_id=ord-1")

    assert response.status_code == 200
    assert b"ord-1" in response.content


@pytest.mark.django_db
def test_success_not_found_returns_404(client):
    """Payment 不在 → 404."""
    response = client.get("/payment/checkout/success/?order_id=missing")

    assert response.status_code == 404


@pytest.mark.django_db
def test_success_missing_order_id_returns_404(client):
    """order_id なし → 404 (空文字で検索 → 不在)."""
    response = client.get("/payment/checkout/success/")

    assert response.status_code == 404


# ============================================================================
# cancel_view
# ============================================================================

@pytest.mark.django_db
def test_cancel_pending_marks_canceled(client):
    """PENDING → CANCELED に更新 + 200."""
    payment = PaymentFactory(
        order_id="ord-1",
        session_status=Payment.SessionStatus.PENDING,
    )

    response = client.get("/payment/checkout/cancel/?order_id=ord-1")

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.session_status == Payment.SessionStatus.CANCELED


@pytest.mark.django_db
def test_cancel_completed_not_overwritten(client):
    """COMPLETED は CANCELED で上書きしない (succeeded が真)."""
    payment = PaymentFactory(
        order_id="ord-1",
        session_status=Payment.SessionStatus.COMPLETED,
    )

    response = client.get("/payment/checkout/cancel/?order_id=ord-1")

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.session_status == Payment.SessionStatus.COMPLETED


@pytest.mark.django_db
def test_cancel_expired_not_overwritten(client):
    """EXPIRED も上書きしない."""
    payment = PaymentFactory(
        order_id="ord-1",
        session_status=Payment.SessionStatus.EXPIRED,
    )

    response = client.get("/payment/checkout/cancel/?order_id=ord-1")

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.session_status == Payment.SessionStatus.EXPIRED


@pytest.mark.django_db
def test_cancel_not_found_returns_404(client):
    """Payment 不在 → 404."""
    response = client.get("/payment/checkout/cancel/?order_id=missing")

    assert response.status_code == 404
