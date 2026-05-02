"""create_checkout_view (POST /payment/checkout/) の HTTP テスト.

view 自体のロジックは「JSON parse → URL 組み立て → service 呼び出し → 例外を HTTP status に
マッピング」だけ. ロジックは service 層の test で検証済なので、ここでは HTTP IO に集中.
"""

import json

import pytest
from django.test import Client

from payment.stripe import (
    CreateCheckoutSessionOutput,
    PaymentConfigError,
    PaymentSystemError,
)


def _post_checkout(client: Client, body: dict | str) -> object:
    """共通の POST 呼び出し. body が dict なら JSON 化、str ならそのまま送る."""
    payload = json.dumps(body) if isinstance(body, dict) else body
    return client.post("/payment/checkout/", data=payload, content_type="application/json")


def _valid_body() -> dict:
    return {
        "order_id": "ord-1",
        "company_id": "cmp-1",
        "company_name": "Acme",
        "amount": 1000,
        "description": "Product",
    }


@pytest.mark.django_db
def test_returns_url_on_success(client, mock_stripe_client):
    """happy path: 200 + JSON {url}."""
    mock_stripe_client.create_customer.return_value = "cus_x"
    mock_stripe_client.create_checkout_session.return_value = CreateCheckoutSessionOutput(
        session_id="cs_x", url="https://stripe.example/c",
    )

    response = _post_checkout(client, _valid_body())

    assert response.status_code == 200
    assert response.json() == {"url": "https://stripe.example/c"}


def test_invalid_json_returns_400(client):
    """JSON 不正 → 400."""
    response = _post_checkout(client, "not-json{")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_json"


@pytest.mark.django_db
def test_missing_field_returns_400(client, mock_stripe_client):
    """必須 field 欠落 (空文字) → InvalidInputError → 400."""
    body = _valid_body()
    body["order_id"] = ""

    response = _post_checkout(client, body)

    assert response.status_code == 400
    assert "error" in response.json()
    # service / Stripe は呼ばれてない
    mock_stripe_client.create_customer.assert_not_called()


@pytest.mark.django_db
def test_amount_non_positive_returns_400(client):
    """amount=0 → InvalidInputError → 400."""
    body = _valid_body()
    body["amount"] = 0

    response = _post_checkout(client, body)

    assert response.status_code == 400


@pytest.mark.django_db
def test_stripe_transient_returns_502(client, mock_stripe_client):
    """PaymentSystemError → 502."""
    mock_stripe_client.create_customer.side_effect = PaymentSystemError("transient")

    response = _post_checkout(client, _valid_body())

    assert response.status_code == 502
    assert response.json() == {"error": "stripe_transient"}


@pytest.mark.django_db
def test_stripe_permanent_returns_500(client, mock_stripe_client):
    """PaymentConfigError → 500."""
    mock_stripe_client.create_customer.side_effect = PaymentConfigError("permanent")

    response = _post_checkout(client, _valid_body())

    assert response.status_code == 500
    assert response.json() == {"error": "stripe_permanent"}
