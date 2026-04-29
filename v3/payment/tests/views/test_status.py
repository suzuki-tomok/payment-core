"""status_view (GET /payment/status/) の HTTP テスト.

success.html の JS が polling する内部 API. JSON で status / amount / description を返す.
"""

import pytest

from payment.models import Payment
from payment.tests.factories import PaymentFactory


@pytest.mark.django_db
def test_status_returns_json(client):
    """Payment 存在 → 200 + JSON {status, amount, description}."""
    PaymentFactory(
        order_id="ord-1",
        amount=1500,
        description="Product A",
        session_status=Payment.SessionStatus.PENDING,
        payment_status=Payment.PaymentStatus.UNPAID,
    )

    response = client.get("/payment/status/?order_id=ord-1")

    assert response.status_code == 200
    assert response.json() == {
        "status": "pending",
        "amount": 1500,
        "description": "Product A",
    }


@pytest.mark.django_db
def test_status_missing_order_id_returns_400(client):
    """order_id クエリ無し → 400."""
    response = client.get("/payment/status/")

    assert response.status_code == 400
    assert response.json() == {"error": "order_id required"}


@pytest.mark.django_db
def test_status_not_found_returns_404(client):
    """Payment 不在 → 404."""
    response = client.get("/payment/status/?order_id=missing")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


@pytest.mark.django_db
def test_status_succeeded_returned(client):
    """SUCCEEDED の Payment → status=succeeded."""
    PaymentFactory(
        order_id="ord-1",
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.SUCCEEDED,
    )

    response = client.get("/payment/status/?order_id=ord-1")

    assert response.json()["status"] == "succeeded"
